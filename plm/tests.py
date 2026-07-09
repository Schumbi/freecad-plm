import json
from datetime import date, timedelta
from hashlib import sha256
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.urls import reverse
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from .auth import create_api_token
from .fcstd import fcstd_with_plm_revision, validate_fcstd_upload
from .fcstd_signature import fcstd_document_signature
from .models import (
    Annotation,
    ApiToken,
    AuditEvent,
    Checkout,
    ExportJob,
    ManufacturingFile,
    ManufacturingMachine,
    ManufacturingRun,
    ManufacturingRunAttachment,
    Part,
    Project,
    ProjectSnapshot,
    ProjectSnapshotEntry,
    Revision,
    RevisionArtifact,
)
from .permissions import (
    can_edit_revision_notes,
    ROLE_ADMIN,
    ROLE_EDITOR,
    ROLE_READER,
    can_release_revision,
    can_upload_revision,
)
from .services import (
    PLMRevisionConflict,
    create_checkout,
    create_manufacturing_file_from_upload,
    create_revision_from_upload,
    import_project_snapshot,
    next_revision_code,
    release_revision,
)
from .freecadcmd import (
    PNG_VIEW_NAMES,
    create_export_job,
    freecadcmd_command,
    process_export_job,
    with_flatpak_worker_options,
)
from .mesh_preview import render_stl_views


FREECAD_DOCUMENT_XML = """
    <Document SchemaVersion="4" ProgramVersion="1.1R1" FileVersion="1">
        <Properties Count="4">
            <Property name="Label" type="App::PropertyString">
                <String value="Testteil aus FreeCAD"/>
            </Property>
            <Property name="License" type="App::PropertyString">
                <String value="CC-BY"/>
            </Property>
                    <Property name="CreatedBy" type="App::PropertyString">
                        <String value="Ralf Warmuth"/>
                    </Property>
                    <Property name="Id" type="App::PropertyString">
                        <String value="FC-P-123"/>
                    </Property>
                    <Property name="PLMRevision" type="App::PropertyString">
                        <String value="R0001"/>
                    </Property>
                    <Property name="Uid" type="App::PropertyUUID">
                        <Uuid value="11111111-2222-3333-4444-555555555555"/>
            </Property>
        </Properties>
    </Document>
"""


def write_zip_member(archive, name, content):
    info = ZipInfo(name)
    info.date_time = (2026, 1, 1, 0, 0, 0)
    archive.writestr(info, content)


def replace_zip_member(data, member_name, transform):
    buffer = BytesIO()
    with ZipFile(BytesIO(data)) as source, ZipFile(buffer, "w") as target:
        for info in source.infolist():
            content = source.read(info.filename)
            if info.filename == member_name:
                content = transform(content)
            write_zip_member(target, info.filename, content)
    return buffer.getvalue()


def make_zip_upload(name="part.FCStd", members=None):
    members = members or {
        "Document.xml": FREECAD_DOCUMENT_XML,
    }
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for member_name, content in members.items():
            write_zip_member(archive, member_name, content)
    return SimpleUploadedFile(name, buffer.getvalue())


class UploadWithoutReportedSize(BytesIO):
    def __init__(self, name, data):
        super().__init__(data)
        self.name = name

    def chunks(self, chunk_size=64 * 1024):
        self.seek(0)
        while True:
            chunk = self.read(chunk_size)
            if not chunk:
                break
            yield chunk
        self.seek(0)


def make_3mf_upload(name="plate.3mf", members=None):
    members = members or {
        "3D/3dmodel.model": "<model unit=\"millimeter\"></model>",
        "Metadata/project_settings.config": """
            printer_model = Bambu Lab X1C
            print_settings_id = 0.20mm Standard @BBL X1C
            filament_type = PETG
            filament_vendor = Bambu Lab
            nozzle_diameter = 0.4
            layer_height = 0.2
        """,
        "Metadata/thumbnail.png": b"\x89PNG\r\n\x1a\n",
    }
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for member_name, content in members.items():
            write_zip_member(archive, member_name, content)
    return SimpleUploadedFile(name, buffer.getvalue())


def make_bambu_json_3mf_upload(name="bambu.3mf"):
    return make_3mf_upload(
        name=name,
        members={
            "3D/3dmodel.model": "<model unit=\"millimeter\"></model>",
            "Metadata/project_settings.config": json.dumps(
                {
                    "printer_model": "Bambu Lab A1",
                    "print_settings_id": "0.08mm Extra Fine @BBL A1",
                    "filament_type": ["PLA", "PLA", "ABS"],
                    "filament_vendor": ["SUNLU", "Bambu Lab", "Bambu Lab"],
                    "nozzle_diameter": ["0.4"],
                    "layer_height": "0.08",
                }
            ),
            "Metadata/slice_info.config": """
                <?xml version="1.0" encoding="UTF-8"?>
                <config>
                  <header>
                    <header_item key="X-BBL-Client-Type" value="slicer"/>
                    <header_item key="X-BBL-Client-Version" value="02.07.01.57"/>
                  </header>
                </config>
            """,
            "Metadata/plate_1.json": json.dumps(
                {
                    "nozzle_diameter": 0.4,
                    "layer_height": 0.2,
                    "bed_type": "hot_plate",
                }
            ),
            "Metadata/plate_1.png": b"\x89PNG\r\n\x1a\n",
        },
    )


def freecad_document_xml(label, freecad_id="", object_type="PartDesign::Body", xlinks=None):
    xlinks = xlinks or []
    xlink_xml = "\n".join(
        f'<XLink file="{file_name}" name="{name}"/>' for file_name, name in xlinks
    )
    return f"""
        <Document SchemaVersion="4" ProgramVersion="1.1R1" FileVersion="1">
            <Properties Count="2">
                <Property name="Label" type="App::PropertyString">
                    <String value="{label}"/>
                </Property>
                <Property name="Id" type="App::PropertyString">
                    <String value="{freecad_id}"/>
                </Property>
            </Properties>
            <Objects Count="1">
                <Object type="{object_type}" name="{label}" id="1" />
            </Objects>
            <ObjectData Count="1">
                <Object name="{label}">
                    <Properties Count="1">
                        <Property name="LinkedObject" type="App::PropertyXLink">
                            {xlink_xml}
                        </Property>
                    </Properties>
                </Object>
            </ObjectData>
        </Document>
    """


def make_fcstd_bytes(label, freecad_id="", object_type="PartDesign::Body", xlinks=None):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        write_zip_member(
            archive,
            "Document.xml",
            freecad_document_xml(label, freecad_id, object_type, xlinks),
        )
    return buffer.getvalue()


def make_project_zip_upload(name="project.zip", members=None):
    members = members or {
        "Chip.FCStd": make_fcstd_bytes("Chip", object_type="App::VarSet"),
        "Box.FCStd": make_fcstd_bytes("Box", xlinks=[("Chip.FCStd", "VarSet")]),
        "Deckel.FCStd": make_fcstd_bytes(
            "Deckel",
            xlinks=[("Chip.FCStd", "VarSet")],
        ),
        "Druck.FCStd": make_fcstd_bytes(
            "Druck",
            object_type="Assembly::AssemblyObject",
            xlinks=[("Box.FCStd", "Body"), ("Deckel.FCStd", "Body")],
        ),
        "Zusammenbau.FCStd": make_fcstd_bytes(
            "Zusammenbau",
            object_type="Assembly::AssemblyObject",
            xlinks=[("Box.FCStd", "Body"), ("Deckel.FCStd", "Body")],
        ),
    }
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for member_name, content in members.items():
            write_zip_member(archive, member_name, content)
    return SimpleUploadedFile(name, buffer.getvalue())


def fcstd_upload_from_bytes(data, name="part.FCStd"):
    return SimpleUploadedFile(name, data)


def noisy_fcstd_bytes(data, plm_revision="R0099"):
    updated = fcstd_with_plm_revision(data, plm_revision)
    buffer = BytesIO()
    with ZipFile(BytesIO(updated)) as source, ZipFile(buffer, "w") as target:
        for info in source.infolist():
            content = source.read(info.filename)
            if info.filename == "Document.xml":
                content = content.replace(
                    b"<Document",
                    b'<Document status="1" stamp="2" Touched="1"',
                    1,
                )
            write_zip_member(target, info.filename, content)
        write_zip_member(target, "GuiDocument.xml", "<GuiDocument><Camera /></GuiDocument>")
        write_zip_member(target, "Body.brp", b"rewritten-cache")
    return buffer.getvalue()


class FcstdValidationTests(SimpleTestCase):
    def test_accepts_fcstd_zip_and_returns_metadata(self):
        upload = make_zip_upload(
            members={
                "Document.xml": FREECAD_DOCUMENT_XML,
                "GuiDocument.xml": "<GuiDocument />",
            },
        )

        metadata = validate_fcstd_upload(upload)

        self.assertEqual(metadata["original_filename"], "part.FCStd")
        self.assertEqual(metadata["zip_member_count"], 2)
        self.assertTrue(metadata["has_document_xml"])
        self.assertTrue(metadata["has_gui_document_xml"])
        self.assertEqual(
            metadata["freecad_document"]["properties"]["Label"],
            "Testteil aus FreeCAD",
        )
        self.assertEqual(
            metadata["freecad_document"]["properties"]["License"],
            "CC-BY",
        )
        self.assertEqual(
            metadata["freecad_document"]["properties"]["Id"],
            "FC-P-123",
        )
        self.assertEqual(
            metadata["freecad_document"]["properties"]["PLMRevision"],
            "R0001",
        )
        self.assertEqual(metadata["freecad_document"]["program_version"], "1.1R1")
        self.assertEqual(len(metadata["sha256"]), 64)
        self.assertEqual(
            len(metadata["technical_signature"]["document_xml_sha256"]),
            64,
        )
        self.assertEqual(metadata["technical_signature"]["rules_version"], 2)
        self.assertGreater(metadata["size_bytes"], 0)

    @override_settings(PLM_MAX_FCSTD_UPLOAD_BYTES=32)
    def test_rejects_fcstd_upload_above_size_budget(self):
        upload = SimpleUploadedFile("part.FCStd", b"x" * 64)

        with self.assertRaises(ValidationError) as context:
            validate_fcstd_upload(upload)

        self.assertIn("Upload-Budget", str(context.exception))

    @override_settings(PLM_MAX_ZIP_MEMBERS=1)
    def test_rejects_fcstd_upload_with_too_many_zip_members(self):
        upload = make_zip_upload(
            members={
                "Document.xml": FREECAD_DOCUMENT_XML,
                "GuiDocument.xml": "<GuiDocument />",
            },
        )

        with self.assertRaises(ValidationError) as context:
            validate_fcstd_upload(upload)

        self.assertIn("zu viele ZIP-Mitglieder", str(context.exception))

    def test_rejects_fcstd_upload_with_dangerous_xml(self):
        upload = make_zip_upload(
            members={
                "Document.xml": """<!DOCTYPE foo [
                    <!ENTITY xxe SYSTEM "file:///etc/passwd">
                ]>
                <Document />""",
            },
        )

        with self.assertRaises(ValidationError) as context:
            validate_fcstd_upload(upload)

        self.assertIn("Document.xml konnte nicht gelesen werden", str(context.exception))

    def test_technical_signature_ignores_gui_plm_revision_and_brep_cache(self):
        base = make_fcstd_bytes("Druck", xlinks=[("Box.FCStd", "Body")])
        noisy = noisy_fcstd_bytes(base)

        self.assertEqual(
            fcstd_document_signature(base),
            fcstd_document_signature(noisy),
        )

    def test_technical_signature_ignores_checkout_path_rewrites(self):
        base = make_zip_upload(
            members={
                "Document.xml": """
                    <Document>
                        <ObjectData>
                            <Object name="Bill_of_Materials">
                                <Properties>
                                    <Property name="cells">
                                        <Cells>
                                            <Cell address="D2" content="'/home/ralf/FreeCAD-PLM/localhost-8000/CB/checkout-2/files/Box.FCStd" />
                                        </Cells>
                                    </Property>
                                </Properties>
                            </Object>
                        </ObjectData>
                    </Document>
                """,
            }
        ).read()
        rewritten = replace_zip_member(
            base,
            "Document.xml",
            lambda content: content.replace(
                b"checkout-2/files/Box.FCStd",
                b"checkout-3/files/Box.FCStd",
            ),
        )

        self.assertEqual(
            fcstd_document_signature(base),
            fcstd_document_signature(rewritten),
        )

    def test_technical_signature_ignores_tiny_placement_rounding_noise(self):
        base = make_zip_upload(
            members={
                "Document.xml": """
                    <Document>
                        <ObjectData>
                            <Object name="Body_Deckel">
                                <Properties>
                                    <Property name="Placement">
                                        <PropertyPlacement
                                            Px="0.0000000000045562"
                                            Py="-0.0000000000000167"
                                            Pz="26.6250000000000000"
                                            Q3="1.0000000000000000" />
                                    </Property>
                                </Properties>
                            </Object>
                        </ObjectData>
                    </Document>
                """,
            }
        ).read()
        rewritten = replace_zip_member(
            base,
            "Document.xml",
            lambda content: content.replace(
                b"0.0000000000045562",
                b"0.0000000000045567",
            ).replace(
                b"-0.0000000000000167",
                b"-0.0000000000000191",
            ),
        )

        self.assertEqual(
            fcstd_document_signature(base),
            fcstd_document_signature(rewritten),
        )

    def test_technical_signature_changes_for_model_relevant_document_xml(self):
        base = make_fcstd_bytes("Druck")
        changed = make_fcstd_bytes("Druck geaendert")

        self.assertNotEqual(
            fcstd_document_signature(base),
            fcstd_document_signature(changed),
        )

    def test_can_set_plm_revision_in_document_xml(self):
        upload = make_zip_upload(members={"Document.xml": "<Document />"})

        updated = fcstd_with_plm_revision(upload.read(), "R0007")
        metadata = validate_fcstd_upload(SimpleUploadedFile("part.FCStd", updated))

        self.assertEqual(
            metadata["freecad_document"]["properties"]["PLMRevision"],
            "R0007",
        )

    def test_rejects_wrong_extension(self):
        upload = make_zip_upload(name="part.zip")

        with self.assertRaises(ValidationError):
            validate_fcstd_upload(upload)

    def test_rejects_non_zip_fcstd(self):
        upload = SimpleUploadedFile("part.FCStd", b"not a zip")

        with self.assertRaises(ValidationError):
            validate_fcstd_upload(upload)

    def test_rejects_empty_fcstd(self):
        upload = SimpleUploadedFile("part.FCStd", b"")

        with self.assertRaises(ValidationError):
            validate_fcstd_upload(upload)


class RevisionUploadServiceTests(TestCase):
    def setUp(self):
        self.media_root = TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root.name)
        self.settings_override.enable()

        self.user = get_user_model().objects.create_user(
            username="editor",
            password="test",
        )
        self.project = Project.objects.create(code="PRJ", name="Projekt")
        self.part = Part.objects.create(
            project=self.project,
            number="P-001",
            name="Testteil",
        )

    def tearDown(self):
        self.settings_override.disable()
        self.media_root.cleanup()

    def create_stored_revision(self, revision_code):
        return Revision.objects.create(
            part=self.part,
            revision_code=revision_code,
            file=f"{revision_code or 'invalid'}.FCStd",
            original_filename=f"{revision_code or 'invalid'}.FCStd",
            sha256=f"{Revision.objects.count():064d}",
            size_bytes=1,
            created_by=self.user,
        )

    def test_next_revision_code_starts_at_r0001(self):
        self.assertEqual(next_revision_code(self.part), "R0001")

    def test_next_revision_code_uses_four_digit_format(self):
        self.create_stored_revision("R0009")

        self.assertEqual(next_revision_code(self.part), "R0010")

    def test_next_revision_code_increments_from_highest_existing_code(self):
        self.create_stored_revision("R0001")
        self.create_stored_revision("R0002")

        self.assertEqual(next_revision_code(self.part), "R0003")

    def test_next_revision_code_does_not_reuse_gaps(self):
        self.create_stored_revision("R0001")
        self.create_stored_revision("R0003")

        self.assertEqual(next_revision_code(self.part), "R0004")

    def test_next_revision_code_ignores_invalid_existing_codes(self):
        for code in ["A0009", "R001", "R0000", "R10000", "R12A4", "R-001", ""]:
            self.create_stored_revision(code)
        self.create_stored_revision("R0002")

        self.assertEqual(next_revision_code(self.part), "R0003")

    def test_create_revision_from_upload_stores_revision_metadata_and_audit(self):
        upload = make_zip_upload(
            members={
                "Document.xml": FREECAD_DOCUMENT_XML,
                "GuiDocument.xml": "<GuiDocument />",
            },
        )

        revision = create_revision_from_upload(self.part, upload, self.user)

        self.assertEqual(revision.revision_code, "R0001")
        self.assertEqual(revision.status, Revision.Status.DRAFT)
        self.assertEqual(revision.original_filename, "part.FCStd")
        self.assertEqual(len(revision.sha256), 64)
        self.assertGreater(revision.size_bytes, 0)
        self.assertEqual(revision.extracted_metadata["zip_member_count"], 2)
        self.assertTrue(revision.extracted_metadata["has_document_xml"])
        self.assertEqual(
            revision.extracted_metadata["freecad_document"]["properties"]["Label"],
            "Testteil aus FreeCAD",
        )
        self.assertEqual(
            revision.extracted_metadata["freecad_document"]["properties"]["License"],
            "CC-BY",
        )
        self.assertEqual(
            revision.extracted_metadata["freecad_document"]["properties"]["Id"],
            "FC-P-123",
        )
        self.assertTrue(revision.file.storage.exists(revision.file.name))
        self.assertEqual(AuditEvent.objects.count(), 1)

    def test_create_revision_from_upload_increments_revision_code(self):
        create_revision_from_upload(self.part, make_zip_upload(), self.user)

        revision = create_revision_from_upload(
            self.part,
            make_zip_upload(
                members={
                    "Document.xml": """
                        <Document changed="yes">
                            <Properties Count="1">
                                <Property name="PLMRevision" type="App::PropertyString">
                                    <String value="R0002"/>
                                </Property>
                            </Properties>
                        </Document>
                    """,
                }
            ),
            self.user,
        )

        self.assertEqual(revision.revision_code, "R0002")

    def test_missing_plm_revision_raises_conflict_without_normalization(self):
        upload = make_zip_upload(members={"Document.xml": "<Document />"})

        with self.assertRaises(PLMRevisionConflict) as context:
            create_revision_from_upload(self.part, upload, self.user)

        self.assertEqual(context.exception.expected, "R0001")
        self.assertEqual(context.exception.actual, "")
        self.assertFalse(Revision.objects.exists())

    def test_normalization_adds_plm_revision_and_audits_original_hash(self):
        upload = make_zip_upload(members={"Document.xml": "<Document />"})
        original_hash = validate_fcstd_upload(upload)["sha256"]

        revision = create_revision_from_upload(
            self.part,
            upload,
            self.user,
            normalize_plm_revision=True,
        )

        stored_metadata = validate_fcstd_upload(revision.file)
        self.assertEqual(
            stored_metadata["freecad_document"]["properties"]["PLMRevision"],
            "R0001",
        )
        self.assertNotEqual(revision.sha256, original_hash)
        self.assertTrue(revision.extracted_metadata["plm_revision"]["normalized"])
        self.assertEqual(
            revision.extracted_metadata["plm_revision"]["original_upload_sha256"],
            original_hash,
        )
        self.assertEqual(
            AuditEvent.objects.get().metadata["plm_revision"]["original_upload_sha256"],
            original_hash,
        )

    def test_wrong_plm_revision_raises_conflict(self):
        upload = make_zip_upload(
            members={
                "Document.xml": """
                    <Document>
                        <Properties Count="1">
                            <Property name="PLMRevision" type="App::PropertyString">
                                <String value="R0099"/>
                            </Property>
                        </Properties>
                    </Document>
                """,
            }
        )

        with self.assertRaises(PLMRevisionConflict) as context:
            create_revision_from_upload(self.part, upload, self.user)

        self.assertEqual(context.exception.expected, "R0001")
        self.assertEqual(context.exception.actual, "R0099")

    def test_duplicate_file_for_same_part_is_rejected(self):
        create_revision_from_upload(self.part, make_zip_upload(), self.user)

        with self.assertRaises(ValidationError):
            create_revision_from_upload(self.part, make_zip_upload(), self.user)

        self.assertEqual(Revision.objects.count(), 1)

    def test_invalid_upload_does_not_create_revision(self):
        upload = SimpleUploadedFile("part.FCStd", b"not a zip")

        with self.assertRaises(ValidationError):
            create_revision_from_upload(self.part, upload, self.user)

        self.assertFalse(Revision.objects.exists())
        self.assertFalse(AuditEvent.objects.exists())

    def test_import_project_snapshot_creates_entries_and_revisions(self):
        snapshot = import_project_snapshot(
            self.project,
            make_project_zip_upload("Sommerrodelbahn-Chipbox.zip"),
            self.user,
        )

        self.assertEqual(snapshot.name, "Sommerrodelbahn-Chipbox")
        self.assertEqual(snapshot.entries.count(), 5)
        self.assertEqual(Revision.objects.count(), 5)
        self.assertEqual(Part.objects.get(name="Chip").number, "P-002")
        self.assertEqual(Part.objects.get(name="Box").number, "P-003")
        self.assertEqual(Part.objects.get(name="Deckel").number, "P-004")
        self.assertEqual(Part.objects.get(name="Druck").number, "A-001")
        self.assertEqual(Part.objects.get(name="Zusammenbau").number, "A-002")
        self.assertEqual(Part.objects.get(name="Chip").category, Part.Category.PART)
        druck = Part.objects.get(name="Druck")
        self.assertEqual(druck.category, Part.Category.ASSEMBLY)
        druck_revision = druck.revisions.get()
        self.assertEqual(
            druck_revision.extracted_metadata["freecad_document"]["document_kind"],
            "assembly",
        )
        self.assertEqual(
            {
                reference["file"]
                for reference in druck_revision.extracted_metadata["freecad_document"][
                    "references"
                ]
            },
            {"Box.FCStd", "Deckel.FCStd"},
        )

    def test_import_project_snapshot_reuses_unchanged_revision(self):
        first = import_project_snapshot(
            self.project,
            make_project_zip_upload("first.zip"),
            self.user,
        )
        second = import_project_snapshot(
            self.project,
            make_project_zip_upload("second.zip"),
            self.user,
        )

        self.assertEqual(first.entries.count(), 5)
        self.assertEqual(second.entries.count(), 5)
        self.assertEqual(Revision.objects.count(), 5)
        self.assertEqual(second.import_summary["created_revisions"], 0)
        self.assertEqual(second.import_summary["reused_revisions"], 5)

    def test_import_project_snapshot_uses_freecad_id_as_part_number(self):
        import_project_snapshot(
            self.project,
            make_project_zip_upload(
                "identified.zip",
                members={
                    "Box.FCStd": make_fcstd_bytes(
                        "Box",
                        freecad_id="FC-BOX-001",
                    ),
                    "Druck.FCStd": make_fcstd_bytes(
                        "Druck",
                        freecad_id="ASM-DRUCK-001",
                        object_type="Assembly::AssemblyObject",
                    ),
                },
            ),
            self.user,
        )

        self.assertEqual(Part.objects.get(name="Box").number, "FC-BOX-001")
        self.assertEqual(Part.objects.get(name="Druck").number, "ASM-DRUCK-001")

    def test_import_project_snapshot_numbers_parts_and_assemblies_separately(self):
        project = Project.objects.create(code="EMPTY", name="Leeres Projekt")

        import_project_snapshot(
            project,
            make_project_zip_upload(
                "mixed.zip",
                members={
                    "Box.FCStd": make_fcstd_bytes("Box"),
                    "Deckel.FCStd": make_fcstd_bytes("Deckel"),
                    "Druck.FCStd": make_fcstd_bytes(
                        "Druck",
                        object_type="Assembly::AssemblyObject",
                    ),
                },
            ),
            self.user,
        )

        self.assertEqual(project.parts.get(name="Box").number, "P-001")
        self.assertEqual(project.parts.get(name="Deckel").number, "P-002")
        self.assertEqual(project.parts.get(name="Druck").number, "A-001")

    def test_import_project_snapshot_creates_revision_for_changed_member_only(self):
        import_project_snapshot(
            self.project,
            make_project_zip_upload("first.zip"),
            self.user,
        )
        changed_box = make_fcstd_bytes("Box geaendert")

        second = import_project_snapshot(
            self.project,
            make_project_zip_upload(
                "second.zip",
                members={
                    "Chip.FCStd": make_fcstd_bytes("Chip", object_type="App::VarSet"),
                    "Box.FCStd": changed_box,
                    "Deckel.FCStd": make_fcstd_bytes(
                        "Deckel",
                        xlinks=[("Chip.FCStd", "VarSet")],
                    ),
                    "Druck.FCStd": make_fcstd_bytes(
                        "Druck",
                        object_type="Assembly::AssemblyObject",
                        xlinks=[("Box.FCStd", "Body"), ("Deckel.FCStd", "Body")],
                    ),
                    "Zusammenbau.FCStd": make_fcstd_bytes(
                        "Zusammenbau",
                        object_type="Assembly::AssemblyObject",
                        xlinks=[("Box.FCStd", "Body"), ("Deckel.FCStd", "Body")],
                    ),
                },
            ),
            self.user,
        )

        self.assertEqual(Revision.objects.count(), 6)
        self.assertEqual(Part.objects.get(name="Box").revisions.count(), 2)
        self.assertEqual(
            second.entries.get(path="Box.FCStd").revision.revision_code,
            "R0002",
        )
        self.assertEqual(
            second.entries.get(path="Chip.FCStd").revision.revision_code,
            "R0001",
        )
        self.assertEqual(second.import_summary["created_revisions"], 1)
        self.assertEqual(second.import_summary["reused_revisions"], 4)

    @override_settings(PLM_MAX_ZIP_MEMBERS=1)
    def test_import_project_snapshot_rejects_zip_with_too_many_members(self):
        with self.assertRaises(ValidationError) as context:
            import_project_snapshot(
                self.project,
                make_project_zip_upload(),
                self.user,
            )

        self.assertIn("zu viele ZIP-Mitglieder", str(context.exception))

    def test_import_project_snapshot_rejects_zip_above_size_budget_without_size_attribute(self):
        data = make_project_zip_upload().read()
        upload = UploadWithoutReportedSize("project.zip", data)

        with override_settings(PLM_MAX_PROJECT_ZIP_BYTES=len(data) - 1):
            with self.assertRaises(ValidationError) as context:
                import_project_snapshot(self.project, upload, self.user)

        self.assertIn("Upload-Budget", str(context.exception))

    def test_release_revision_sets_status_timestamp_and_audit(self):
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)
        AuditEvent.objects.all().delete()

        release_revision(revision, self.user)

        revision.refresh_from_db()
        self.assertEqual(revision.status, Revision.Status.RELEASED)
        self.assertIsNotNone(revision.released_at)
        self.assertEqual(
            AuditEvent.objects.get().action,
            AuditEvent.Action.REVISION_RELEASED,
        )

    def test_release_revision_rejects_already_released_revision(self):
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)
        release_revision(revision, self.user)

        with self.assertRaises(ValidationError):
            release_revision(revision, self.user)


class RevisionUploadViewTests(TestCase):
    def setUp(self):
        self.media_root = TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root.name)
        self.settings_override.enable()

        self.user = get_user_model().objects.create_user(
            username="viewer",
            password="test",
            is_superuser=True,
        )
        self.project = Project.objects.create(code="PRJ", name="Projekt")
        self.part = Part.objects.create(
            project=self.project,
            number="P-001",
            name="Testteil",
        )

    def tearDown(self):
        self.settings_override.disable()
        self.media_root.cleanup()

    def create_second_revision(self):
        return create_revision_from_upload(
            self.part,
            make_zip_upload(
                members={
                    "Document.xml": FREECAD_DOCUMENT_XML.replace(
                        "Testteil aus FreeCAD",
                        "Testteil geaendert",
                    )
                }
            ),
            self.user,
            normalize_plm_revision=True,
        )

    def create_png_artifacts(self, revision):
        for view_name in PNG_VIEW_NAMES:
            content = b"\x89PNG\r\n\x1a\n"
            RevisionArtifact.objects.create(
                revision=revision,
                artifact_type=RevisionArtifact.ArtifactType.PNG,
                view_name=view_name,
                file=ContentFile(content, name=f"{revision.revision_code}-{view_name}.png"),
                original_filename=f"{revision.revision_code}-{view_name}.png",
                sha256=f"{revision.id:032d}{len(view_name):032d}",
                size_bytes=len(content),
            )

    def create_viewer_stl_artifact(self, revision):
        content = (
            b"solid triangle\n"
            b"facet normal 0 0 1\n"
            b"outer loop\n"
            b"vertex 0 0 0\n"
            b"vertex 1 0 0\n"
            b"vertex 0 1 0\n"
            b"endloop\n"
            b"endfacet\n"
            b"endsolid triangle\n"
        )
        return RevisionArtifact.objects.create(
            revision=revision,
            artifact_type=RevisionArtifact.ArtifactType.STL,
            view_name="viewer-preview",
            file=ContentFile(content, name="preview.stl"),
            original_filename="preview.stl",
            sha256="b" * 64,
            size_bytes=len(content),
        )

    def test_project_list_requires_login(self):
        response = self.client.get(reverse("plm:project_list"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_part_detail_shows_upload_form(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("plm:part_detail", args=[self.part.id]))

        self.assertContains(response, "Neue Revision hochladen")
        self.assertContains(response, "Revision hochladen")

    def test_part_detail_shows_freecad_metadata(self):
        create_revision_from_upload(self.part, make_zip_upload(), self.user)
        self.client.force_login(self.user)

        response = self.client.get(reverse("plm:part_detail", args=[self.part.id]))

        self.assertContains(response, "Testteil aus FreeCAD")
        self.assertContains(response, "CC-BY")
        self.assertContains(response, "1.1R1")

    def test_part_detail_shows_3d_viewer_buttons(self):
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)
        RevisionArtifact.objects.create(
            revision=revision,
            artifact_type=RevisionArtifact.ArtifactType.STL,
            file=ContentFile(b"solid model\nendsolid model\n", name="artifact.stl"),
            original_filename="artifact.stl",
            sha256="c" * 64,
            size_bytes=25,
        )
        create_manufacturing_file_from_upload(
            revision=revision,
            uploaded_file=make_3mf_upload(),
            uploaded_by=self.user,
            label="Slicer-Datei",
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("plm:part_detail", args=[self.part.id]))

        self.assertContains(response, "3D anzeigen")
        self.assertContains(response, reverse("plm:revision_viewer_source", args=[revision.id]))
        self.assertContains(response, reverse("plm:create_revision_viewer_preview", args=[revision.id]))
        self.assertContains(response, reverse("plm:revision_viewer_status", args=[revision.id]))
        artifact = RevisionArtifact.objects.get(original_filename="artifact.stl")
        self.assertContains(response, reverse("plm:artifact_viewer_source", args=[artifact.id]))
        manufacturing_file = ManufacturingFile.objects.get()
        self.assertContains(
            response,
            reverse("plm:manufacturing_file_viewer_source", args=[manufacturing_file.id]),
        )

    def test_upload_revision_creates_revision(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("plm:upload_revision", args=[self.part.id]),
            {"file": make_zip_upload()},
        )

        self.assertRedirects(response, reverse("plm:part_detail", args=[self.part.id]))
        revision = Revision.objects.get()
        self.assertEqual(revision.revision_code, "R0001")
        self.assertEqual(revision.created_by, self.user)
        self.assertEqual(
            set(revision.export_jobs.values_list("job_type", flat=True)),
            {ExportJob.JobType.INSPECT, ExportJob.JobType.PNG_VIEWS},
        )
        self.assertEqual(AuditEvent.objects.count(), 3)

    def test_duplicate_upload_shows_error_and_creates_no_new_revision(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("plm:upload_revision", args=[self.part.id]),
            {"file": make_zip_upload()},
        )

        response = self.client.post(
            reverse("plm:upload_revision", args=[self.part.id]),
            {"file": make_zip_upload()},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "bereits hochgeladen", status_code=400)
        self.assertEqual(Revision.objects.count(), 1)

    def test_invalid_upload_shows_error_and_creates_no_revision(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("plm:upload_revision", args=[self.part.id]),
            {"file": SimpleUploadedFile("part.FCStd", b"not a zip")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "gueltiges ZIP-Archiv", status_code=400)
        self.assertFalse(Revision.objects.exists())
        self.assertFalse(AuditEvent.objects.exists())

    def test_missing_plm_revision_shows_confirmation_page(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("plm:upload_revision", args=[self.part.id]),
            {"file": make_zip_upload(members={"Document.xml": "<Document />"})},
        )

        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "PLMRevision pruefen", status_code=409)
        self.assertContains(response, "R0001", status_code=409)
        self.assertContains(response, "keine PLMRevision", status_code=409)
        self.assertFalse(Revision.objects.exists())

    def test_pending_plm_revision_upload_can_be_discarded(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("plm:upload_revision", args=[self.part.id]),
            {"file": make_zip_upload(members={"Document.xml": "<Document />"})},
        )

        response = self.client.post(
            reverse("plm:confirm_revision_upload", args=[self.part.id]),
            {"action": "discard"},
        )

        self.assertRedirects(response, reverse("plm:part_detail", args=[self.part.id]))
        self.assertFalse(Revision.objects.exists())

    def test_pending_plm_revision_upload_can_be_normalized(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("plm:upload_revision", args=[self.part.id]),
            {"file": make_zip_upload(members={"Document.xml": "<Document />"})},
        )

        response = self.client.post(
            reverse("plm:confirm_revision_upload", args=[self.part.id]),
            {"action": "normalize"},
        )

        self.assertRedirects(response, reverse("plm:part_detail", args=[self.part.id]))
        revision = Revision.objects.get()
        metadata = validate_fcstd_upload(revision.file)
        self.assertEqual(
            metadata["freecad_document"]["properties"]["PLMRevision"],
            "R0001",
        )
        self.assertTrue(revision.extracted_metadata["plm_revision"]["normalized"])
        self.assertEqual(revision.export_jobs.count(), 2)

    def test_download_revision_requires_login(self):
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)

        response = self.client.get(reverse("plm:download_revision", args=[revision.id]))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_download_revision_returns_file_and_audits_download(self):
        self.client.force_login(self.user)
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)
        AuditEvent.objects.all().delete()

        response = self.client.get(reverse("plm:download_revision", args=[revision.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="part.FCStd"',
        )
        self.assertEqual(
            AuditEvent.objects.get().action,
            AuditEvent.Action.REVISION_DOWNLOADED,
        )
        response.close()

    def test_png_views_button_processes_job_immediately(self):
        self.client.force_login(self.user)
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)

        def mark_succeeded(job):
            job.status = ExportJob.Status.SUCCEEDED
            job.save(update_fields=["status", "updated_at"])
            return job

        with patch("plm.views.process_export_job", side_effect=mark_succeeded) as process:
            response = self.client.post(
                reverse("plm:create_revision_png_job", args=[revision.id])
            )

        self.assertRedirects(response, reverse("plm:part_detail", args=[self.part.id]))
        job = ExportJob.objects.get()
        self.assertEqual(job.job_type, ExportJob.JobType.PNG_VIEWS)
        self.assertEqual(job.status, ExportJob.Status.SUCCEEDED)
        process.assert_called_once_with(job)

    def test_png_views_button_only_queues_job_when_inline_processing_is_disabled(self):
        self.client.force_login(self.user)
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)

        with (
            override_settings(PROCESS_EXPORT_JOBS_INLINE=False),
            patch("plm.views.process_export_job") as process,
        ):
            response = self.client.post(
                reverse("plm:create_revision_png_job", args=[revision.id])
            )

        self.assertRedirects(response, reverse("plm:part_detail", args=[self.part.id]))
        job = ExportJob.objects.get()
        self.assertEqual(job.job_type, ExportJob.JobType.PNG_VIEWS)
        self.assertEqual(job.status, ExportJob.Status.QUEUED)
        process.assert_not_called()

    def test_viewer_preview_button_uses_png_preview_pipeline(self):
        self.client.force_login(self.user)
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)

        with patch("plm.views.ensure_revision_viewer_preview", return_value="queued") as ensure:
            response = self.client.post(
                reverse("plm:create_revision_viewer_preview", args=[revision.id])
            )

        self.assertRedirects(response, reverse("plm:part_detail", args=[self.part.id]))
        ensure.assert_called_once_with(revision, self.user)

    def test_viewer_preview_ajax_returns_status_payload(self):
        self.client.force_login(self.user)
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)

        with patch("plm.views.ensure_revision_viewer_preview", return_value="queued"):
            response = self.client.post(
                reverse("plm:create_revision_viewer_preview", args=[revision.id]),
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "missing")
        self.assertIn("message", response.json())

    def test_viewer_status_reports_ready_preview(self):
        self.client.force_login(self.user)
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)
        self.create_viewer_stl_artifact(revision)

        response = self.client.get(reverse("plm:revision_viewer_status", args=[revision.id]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(
            payload["source_url"],
            reverse("plm:revision_viewer_source", args=[revision.id]),
        )

    def test_revision_viewer_source_requires_login(self):
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)
        self.create_viewer_stl_artifact(revision)

        response = self.client.get(reverse("plm:revision_viewer_source", args=[revision.id]))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_revision_viewer_source_returns_preview_stl_inline(self):
        self.client.force_login(self.user)
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)
        self.create_viewer_stl_artifact(revision)

        response = self.client.get(reverse("plm:revision_viewer_source", args=[revision.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "model/stl")
        self.assertIn("inline", response["Content-Disposition"])
        response.close()

    def test_revision_viewer_source_reports_missing_preview(self):
        self.client.force_login(self.user)
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)

        response = self.client.get(reverse("plm:revision_viewer_source", args=[revision.id]))

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "keine 3D-Vorschau", status_code=404)

    def test_artifact_viewer_source_returns_direct_stl(self):
        self.client.force_login(self.user)
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)
        artifact = RevisionArtifact.objects.create(
            revision=revision,
            artifact_type=RevisionArtifact.ArtifactType.STL,
            file=ContentFile(b"solid model\nendsolid model\n", name="artifact.stl"),
            original_filename="artifact.stl",
            sha256="d" * 64,
            size_bytes=25,
        )

        response = self.client.get(reverse("plm:artifact_viewer_source", args=[artifact.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "model/stl")
        response.close()

    def test_manufacturing_viewer_source_returns_direct_3mf(self):
        self.client.force_login(self.user)
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)
        manufacturing_file = create_manufacturing_file_from_upload(
            revision=revision,
            uploaded_file=make_3mf_upload(),
            uploaded_by=self.user,
        )

        response = self.client.get(
            reverse("plm:manufacturing_file_viewer_source", args=[manufacturing_file.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "model/3mf")
        response.close()

    def test_revision_compare_queues_missing_png_views_for_selected_revisions(self):
        self.client.force_login(self.user)
        left = create_revision_from_upload(self.part, make_zip_upload(), self.user)
        right = self.create_second_revision()

        with (
            override_settings(PROCESS_EXPORT_JOBS_INLINE=False),
            patch("plm.views.process_export_job") as process,
        ):
            response = self.client.get(
                reverse("plm:revision_compare", args=[self.part.id]),
                {"left": left.id, "right": right.id},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(
                ExportJob.objects.order_by("revision_id").values_list(
                    "revision_id",
                    "job_type",
                    "status",
                )
            ),
            [
                (left.id, ExportJob.JobType.PNG_VIEWS, ExportJob.Status.QUEUED),
                (right.id, ExportJob.JobType.PNG_VIEWS, ExportJob.Status.QUEUED),
            ],
        )
        process.assert_not_called()

    def test_revision_compare_uses_existing_png_views_without_new_jobs(self):
        self.client.force_login(self.user)
        left = create_revision_from_upload(self.part, make_zip_upload(), self.user)
        right = self.create_second_revision()
        self.create_png_artifacts(left)
        self.create_png_artifacts(right)

        with override_settings(PROCESS_EXPORT_JOBS_INLINE=False):
            response = self.client.get(
                reverse("plm:revision_compare", args=[self.part.id]),
                {"left": left.id, "right": right.id},
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ExportJob.objects.exists())
        self.assertContains(response, "front")

    def test_process_export_jobs_button_runs_queued_jobs_once(self):
        self.client.force_login(self.user)
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)
        job = create_export_job(
            revision=revision,
            job_type=ExportJob.JobType.INSPECT,
            created_by=self.user,
        )

        def mark_succeeded():
            job.status = ExportJob.Status.SUCCEEDED
            job.save(update_fields=["status", "updated_at"])
            return [job]

        with patch("plm.views.process_queued_export_jobs", side_effect=mark_succeeded) as process:
            response = self.client.post(
                reverse("plm:process_export_jobs_once", args=[self.part.id])
            )

        self.assertRedirects(response, reverse("plm:part_detail", args=[self.part.id]))
        job.refresh_from_db()
        self.assertEqual(job.status, ExportJob.Status.SUCCEEDED)
        process.assert_called_once_with()

    def test_process_export_jobs_button_does_not_run_in_server_mode(self):
        self.client.force_login(self.user)
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)
        job = create_export_job(
            revision=revision,
            job_type=ExportJob.JobType.INSPECT,
            created_by=self.user,
        )

        with (
            override_settings(PROCESS_EXPORT_JOBS_INLINE=False),
            patch("plm.views.process_queued_export_jobs") as process,
        ):
            response = self.client.post(
                reverse("plm:process_export_jobs_once", args=[self.part.id])
            )

        self.assertRedirects(response, reverse("plm:part_detail", args=[self.part.id]))
        job.refresh_from_db()
        self.assertEqual(job.status, ExportJob.Status.QUEUED)
        process.assert_not_called()

    def test_referenced_revision_without_snapshot_cannot_be_downloaded_alone(self):
        self.client.force_login(self.user)
        revision = create_revision_from_upload(
            self.part,
            make_zip_upload(
                members={
                    "Document.xml": freecad_document_xml(
                        "Druck",
                        xlinks=[("Box.FCStd", "Body")],
                    ),
                }
            ),
            self.user,
            normalize_plm_revision=True,
        )
        AuditEvent.objects.all().delete()

        response = self.client.get(reverse("plm:download_revision", args=[revision.id]))

        self.assertEqual(response.status_code, 403)
        self.assertFalse(AuditEvent.objects.exists())

    def test_referenced_snapshot_revision_download_returns_zip(self):
        self.client.force_login(self.user)
        import_project_snapshot(
            self.project,
            make_project_zip_upload(),
            self.user,
            name="Druckstand",
        )
        druck_revision = Revision.objects.get(
            part__name="Druck",
            extracted_metadata__freecad_document__document_kind="assembly",
        )
        AuditEvent.objects.all().delete()

        response = self.client.get(
            reverse("plm:download_revision", args=[druck_revision.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="PRJ-Druck-with-references.zip"',
        )
        content = b"".join(response.streaming_content)
        with ZipFile(BytesIO(content)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"Box.FCStd", "Chip.FCStd", "Deckel.FCStd", "Druck.FCStd"},
        )
        self.assertEqual(
            AuditEvent.objects.get().metadata["download_mode"],
            "referenced_zip",
        )

    def test_release_revision_requires_login(self):
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)

        response = self.client.post(reverse("plm:release_revision", args=[revision.id]))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_superuser_can_release_revision(self):
        self.client.force_login(self.user)
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)
        AuditEvent.objects.all().delete()

        response = self.client.post(reverse("plm:release_revision", args=[revision.id]))

        self.assertRedirects(response, reverse("plm:part_detail", args=[self.part.id]))
        revision.refresh_from_db()
        self.assertEqual(revision.status, Revision.Status.RELEASED)
        self.assertEqual(
            AuditEvent.objects.get().action,
            AuditEvent.Action.REVISION_RELEASED,
        )

    def test_project_snapshot_upload_and_download_zip(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("plm:upload_project_snapshot", args=[self.project.id]),
            {
                "name": "Druckstand",
                "file": make_project_zip_upload(),
            },
        )

        snapshot = ProjectSnapshot.objects.get()
        self.assertRedirects(
            response,
            reverse("plm:project_detail", args=[self.project.id]),
        )
        self.assertEqual(snapshot.entries.count(), 5)
        self.assertEqual(ExportJob.objects.count(), 10)
        messages = list(response.wsgi_request._messages)
        self.assertIn("5 neue Revisionen", str(messages[0]))
        self.assertIn("0 unveraenderte Dateien", str(messages[0]))
        self.assertIn("10 Analyse-/PNG-Jobs", str(messages[0]))

        response = self.client.get(
            reverse("plm:download_project_snapshot", args=[snapshot.id])
        )

        self.assertEqual(response.status_code, 200)
        content = b"".join(response.streaming_content)
        with ZipFile(BytesIO(content)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {
                    "Box.FCStd",
                    "Chip.FCStd",
                    "Deckel.FCStd",
                    "Druck.FCStd",
                    "Zusammenbau.FCStd",
                },
            )

class RolePermissionTests(TestCase):
    def setUp(self):
        call_command("setup_plm_roles", stdout=StringIO())
        self.reader = get_user_model().objects.create_user(
            username="reader",
            password="test",
        )
        self.reader.groups.add(Group.objects.get(name=ROLE_READER))
        self.editor = get_user_model().objects.create_user(
            username="editor-role",
            password="test",
        )
        self.editor.groups.add(Group.objects.get(name=ROLE_EDITOR))
        self.admin = get_user_model().objects.create_user(
            username="admin-role",
            password="test",
        )
        self.admin.groups.add(Group.objects.get(name=ROLE_ADMIN))
        self.project = Project.objects.create(code="PRJ", name="Projekt")
        self.part = Part.objects.create(
            project=self.project,
            number="P-001",
            name="Testteil",
        )

    def test_reader_cannot_upload_revision(self):
        self.assertFalse(can_upload_revision(self.reader))

        self.client.force_login(self.reader)
        response = self.client.post(
            reverse("plm:upload_revision", args=[self.part.id]),
            {"file": make_zip_upload()},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Revision.objects.exists())

    def test_reader_does_not_see_upload_form(self):
        self.client.force_login(self.reader)

        response = self.client.get(reverse("plm:part_detail", args=[self.part.id]))

        self.assertNotContains(response, "Neue Revision hochladen")
        self.assertNotContains(response, "Revision hochladen")

    def test_admin_sees_project_create_link(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("plm:project_list"))

        self.assertContains(response, "Neues Projekt anlegen")

    def test_admin_can_create_project(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("plm:create_project"),
            {
                "code": "new",
                "name": "Neues Projekt",
                "status": Project.Status.IDEA,
                "project_date": "2026-06-28",
                "description": "Aus der PLM-Oberflaeche.",
            },
        )

        project = Project.objects.get(code="NEW")
        self.assertRedirects(response, reverse("plm:project_detail", args=[project.id]))
        self.assertEqual(project.name, "Neues Projekt")
        self.assertEqual(project.status, Project.Status.IDEA)
        self.assertEqual(project.project_date.isoformat(), "2026-06-28")
        self.assertEqual(
            AuditEvent.objects.filter(action=AuditEvent.Action.PROJECT_CREATED).count(),
            1,
        )

    def test_project_defaults_to_running_and_today(self):
        project = Project.objects.create(code="DEF", name="Default")

        self.assertEqual(project.status, Project.Status.RUNNING)
        self.assertEqual(project.project_date, timezone.localdate())

    def test_project_list_shows_status_and_date(self):
        self.project.status = Project.Status.ORDER
        self.project.project_date = date(2026, 6, 28)
        self.project.save(update_fields=["status", "project_date", "updated_at"])
        self.client.force_login(self.reader)

        response = self.client.get(reverse("plm:project_list"))

        self.assertContains(response, "Auftrag")
        self.assertContains(response, "28.06.2026")

    def test_project_detail_uses_properties_sidebar_and_fallback_page(self):
        self.client.force_login(self.reader)

        response = self.client.get(reverse("plm:project_detail", args=[self.project.id]))
        content = response.content.decode()

        self.assertContains(response, 'class="properties-panel"')
        self.assertContains(response, "Eigenschaften anzeigen")
        self.assertContains(response, "Laufend")
        self.assertLess(
            content.index("Teile und Baugruppen"),
            content.index("Projektstaende"),
        )

        response = self.client.get(reverse("plm:project_properties", args=[self.project.id]))
        self.assertContains(response, "Eigenschaften")
        self.assertContains(response, "Laufend")

    def test_project_detail_shows_edit_button_for_admin(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("plm:project_detail", args=[self.project.id]))

        self.assertContains(response, "Projekt bearbeiten")
        self.assertContains(response, reverse("plm:edit_project", args=[self.project.id]))

    def test_admin_can_edit_project_properties(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("plm:edit_project", args=[self.project.id]),
            {
                "code": "prj",
                "name": "Projekt aktualisiert",
                "status": Project.Status.COMPLETED,
                "project_date": "2026-07-01",
                "description": "Neue Eigenschaften.",
            },
        )

        self.assertRedirects(response, reverse("plm:project_detail", args=[self.project.id]))
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "Projekt aktualisiert")
        self.assertEqual(self.project.status, Project.Status.COMPLETED)
        self.assertEqual(self.project.project_date.isoformat(), "2026-07-01")
        self.assertEqual(
            AuditEvent.objects.filter(action=AuditEvent.Action.PROJECT_UPDATED).count(),
            1,
        )

    def test_editor_cannot_edit_project_properties(self):
        self.client.force_login(self.editor)

        response = self.client.post(
            reverse("plm:edit_project", args=[self.project.id]),
            {
                "code": "prj",
                "name": "Nicht erlaubt",
                "status": Project.Status.IMPORTANT,
                "project_date": "2026-07-01",
                "description": "",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "Projekt")
        self.assertEqual(self.project.status, Project.Status.RUNNING)

    def test_editor_cannot_create_project(self):
        self.client.force_login(self.editor)

        response = self.client.post(
            reverse("plm:create_project"),
            {
                "code": "NEW",
                "name": "Neues Projekt",
                "status": Project.Status.RUNNING,
                "project_date": "2026-06-28",
                "description": "",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Project.objects.filter(code="NEW").exists())

    def test_duplicate_project_code_shows_error(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("plm:create_project"),
            {
                "code": "prj",
                "name": "Doppelt",
                "status": Project.Status.RUNNING,
                "project_date": "2026-06-28",
                "description": "",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "existiert bereits", status_code=400)
        self.assertEqual(Project.objects.filter(code="PRJ").count(), 1)

    def test_admin_sees_management_navigation(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("plm:project_list"))

        self.assertContains(response, "Verwaltung")
        self.assertContains(response, reverse("plm:user_management"))

    def test_reader_cannot_access_user_management(self):
        self.client.force_login(self.reader)

        response = self.client.get(reverse("plm:user_management"))

        self.assertEqual(response.status_code, 403)

    def test_admin_can_create_user_with_role(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("plm:create_user"),
            {
                "username": "new-user",
                "first_name": "New",
                "last_name": "User",
                "email": "new@example.test",
                "is_active": "on",
                "role": ROLE_EDITOR,
                "password": "SehrSicher123!",
            },
        )

        self.assertRedirects(response, reverse("plm:user_management"))
        user = get_user_model().objects.get(username="new-user")
        self.assertTrue(user.check_password("SehrSicher123!"))
        self.assertTrue(user.groups.filter(name=ROLE_EDITOR).exists())
        self.assertEqual(
            AuditEvent.objects.filter(action=AuditEvent.Action.USER_CREATED).count(),
            1,
        )

    def test_admin_can_edit_user_role_and_status(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("plm:edit_user", args=[self.reader.id]),
            {
                "username": self.reader.username,
                "first_name": "Read",
                "last_name": "Only",
                "email": "reader@example.test",
                "is_active": "on",
                "role": ROLE_EDITOR,
                "password": "",
            },
        )

        self.assertRedirects(response, reverse("plm:user_management"))
        self.reader.refresh_from_db()
        self.assertEqual(self.reader.email, "reader@example.test")
        self.assertTrue(self.reader.groups.filter(name=ROLE_EDITOR).exists())
        self.assertFalse(self.reader.groups.filter(name=ROLE_READER).exists())

    def test_admin_cannot_deactivate_self(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("plm:edit_user", args=[self.admin.id]),
            {
                "username": self.admin.username,
                "first_name": "",
                "last_name": "",
                "email": "",
                "role": ROLE_ADMIN,
                "password": "",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_admin_can_set_user_password(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("plm:set_user_password", args=[self.reader.id]),
            {
                "new_password1": "NeuesPasswort123!",
                "new_password2": "NeuesPasswort123!",
            },
        )

        self.assertRedirects(response, reverse("plm:user_management"))
        self.reader.refresh_from_db()
        self.assertTrue(self.reader.check_password("NeuesPasswort123!"))
        self.assertEqual(
            AuditEvent.objects.filter(action=AuditEvent.Action.USER_PASSWORD_SET).count(),
            1,
        )

    def test_admin_can_create_addon_token(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("plm:create_user_token", args=[self.editor.id]),
            {
                "name": "FreeCAD Addon",
                "preset": "addon",
                "expires_at": "",
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertContains(response, "plm_pat_", status_code=201)
        token = ApiToken.objects.get(user=self.editor)
        self.assertEqual(
            token.scopes,
            [ApiToken.Scope.READ, ApiToken.Scope.WRITE, ApiToken.Scope.CHECKOUT],
        )
        self.assertEqual(
            AuditEvent.objects.filter(action=AuditEvent.Action.API_TOKEN_CREATED).count(),
            1,
        )

    def test_admin_preset_requires_admin_user(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("plm:create_user_token", args=[self.editor.id]),
            {
                "name": "Zu viel",
                "preset": "admin",
                "expires_at": "",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Admin/Vollzugriff", status_code=400)
        self.assertFalse(ApiToken.objects.filter(user=self.editor).exists())

    def test_admin_can_revoke_token(self):
        token, _raw_token = create_api_token(
            user=self.editor,
            name="FreeCAD Addon",
            scopes=[ApiToken.Scope.READ],
        )
        self.client.force_login(self.admin)

        response = self.client.post(reverse("plm:revoke_api_token", args=[token.id]))

        self.assertRedirects(response, reverse("plm:user_management"))
        token.refresh_from_db()
        self.assertTrue(token.is_revoked)
        self.assertEqual(
            AuditEvent.objects.filter(action=AuditEvent.Action.API_TOKEN_REVOKED).count(),
            1,
        )

    def test_editor_can_upload_revision(self):
        self.assertTrue(can_upload_revision(self.editor))

        self.client.force_login(self.editor)
        response = self.client.post(
            reverse("plm:upload_revision", args=[self.part.id]),
            {"file": make_zip_upload()},
        )

        self.assertRedirects(response, reverse("plm:part_detail", args=[self.part.id]))
        self.assertEqual(Revision.objects.count(), 1)
        self.assertEqual(ExportJob.objects.count(), 2)

    def test_upload_revision_stores_change_summary_as_notes(self):
        self.client.force_login(self.editor)

        response = self.client.post(
            reverse("plm:upload_revision", args=[self.part.id]),
            {
                "file": make_zip_upload(),
                "change_summary": "Bohrbild auf M4 angepasst.",
            },
        )

        self.assertRedirects(response, reverse("plm:part_detail", args=[self.part.id]))
        revision = Revision.objects.get()
        self.assertEqual(revision.notes, "Bohrbild auf M4 angepasst.")
        self.assertEqual(revision.export_jobs.count(), 2)
        self.assertEqual(
            AuditEvent.objects.get(action=AuditEvent.Action.REVISION_UPLOADED)
            .metadata["change_summary"],
            "Bohrbild auf M4 angepasst.",
        )

    def test_editor_cannot_release_revision(self):
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.editor)
        self.assertFalse(can_release_revision(self.editor))

        self.client.force_login(self.editor)
        response = self.client.post(reverse("plm:release_revision", args=[revision.id]))

        self.assertEqual(response.status_code, 403)
        revision.refresh_from_db()
        self.assertEqual(revision.status, Revision.Status.DRAFT)

    def test_editor_can_update_revision_notes(self):
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.editor)
        AuditEvent.objects.all().delete()
        self.assertTrue(can_edit_revision_notes(self.editor))

        self.client.force_login(self.editor)
        response = self.client.post(
            reverse("plm:update_revision_notes", args=[revision.id]),
            {"notes": "Naechster Schritt: in Baugruppe pruefen."},
        )

        self.assertRedirects(response, reverse("plm:part_detail", args=[self.part.id]))
        revision.refresh_from_db()
        self.assertEqual(revision.notes, "Naechster Schritt: in Baugruppe pruefen.")
        self.assertEqual(
            AuditEvent.objects.get().action,
            AuditEvent.Action.REVISION_NOTES_UPDATED,
        )

    def test_reader_can_see_revision_notes_but_not_edit_form(self):
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.editor)
        revision.notes = "Einbau mit zwei Schrauben."
        revision.save(update_fields=["notes"])

        self.client.force_login(self.reader)
        response = self.client.get(reverse("plm:part_detail", args=[self.part.id]))

        self.assertContains(response, "Einbau mit zwei Schrauben.")
        self.assertNotContains(response, "Speichern")

    def test_revision_notes_and_metadata_open_in_modals(self):
        create_revision_from_upload(self.part, make_zip_upload(), self.editor)

        self.client.force_login(self.reader)
        response = self.client.get(reverse("plm:part_detail", args=[self.part.id]))

        self.assertContains(response, 'data-dialog-target="#notes-')
        self.assertContains(response, 'data-dialog-target="#revision-properties-')
        self.assertContains(response, 'data-dialog-target="#freecad-')
        self.assertContains(response, 'class="plm-dialog"')
        self.assertContains(response, "hidden")
        self.assertNotContains(response, "?properties_revision=")
        self.assertNotContains(response, "<summary>Anmerkungen</summary>")
        self.assertNotContains(response, "<summary>Metadaten</summary>")

    def test_reader_cannot_update_revision_notes(self):
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.editor)
        self.assertFalse(can_edit_revision_notes(self.reader))

        self.client.force_login(self.reader)
        response = self.client.post(
            reverse("plm:update_revision_notes", args=[revision.id]),
            {"notes": "Soll nicht gespeichert werden."},
        )

        self.assertEqual(response.status_code, 403)
        revision.refresh_from_db()
        self.assertEqual(revision.notes, "")

    def test_editor_can_create_part_from_project(self):
        self.client.force_login(self.editor)

        response = self.client.post(
            reverse("plm:create_part", args=[self.project.id]),
            {
                "number": "P-002",
                "name": "Neues Teil",
                "category": Part.Category.PART,
                "description": "Aus der Weboberflaeche angelegt.",
                "material": "PLA",
                "supplier": "",
                "tags": "test",
                "file": make_zip_upload(),
            },
        )

        part = Part.objects.get(number="P-002")
        self.assertRedirects(response, reverse("plm:part_detail", args=[part.id]))
        self.assertEqual(part.project, self.project)
        self.assertEqual(part.name, "Neues Teil")
        self.assertEqual(
            AuditEvent.objects.filter(action=AuditEvent.Action.PART_CREATED).count(),
            1,
        )
        self.assertEqual(part.revisions.count(), 1)
        self.assertEqual(part.revisions.get().revision_code, "R0001")
        self.assertEqual(part.revisions.get().export_jobs.count(), 2)

    def test_empty_part_number_is_generated(self):
        self.client.force_login(self.editor)

        response = self.client.post(
            reverse("plm:create_part", args=[self.project.id]),
            {
                "number": "",
                "name": "Automatisch nummeriert",
                "category": Part.Category.PART,
                "file": make_zip_upload(members={"Document.xml": "<Document />"}),
            },
        )

        part = Part.objects.get(name="Automatisch nummeriert")
        self.assertRedirects(response, reverse("plm:part_detail", args=[part.id]))
        self.assertEqual(part.number, "P-002")
        self.assertEqual(part.revisions.get().export_jobs.count(), 2)

    def test_empty_part_number_uses_freecad_id_when_present(self):
        self.client.force_login(self.editor)

        response = self.client.post(
            reverse("plm:create_part", args=[self.project.id]),
            {
                "number": "",
                "name": "",
                "category": Part.Category.PART,
                "file": make_zip_upload(),
            },
        )

        part = Part.objects.get(number="FC-P-123")
        self.assertRedirects(response, reverse("plm:part_detail", args=[part.id]))
        self.assertEqual(part.name, "Testteil aus FreeCAD")
        self.assertEqual(part.revisions.count(), 1)
        self.assertEqual(part.revisions.get().export_jobs.count(), 2)

    def test_empty_part_number_uses_next_available_p_number(self):
        Part.objects.create(project=self.project, number="P-010", name="Zehn")
        self.client.force_login(self.editor)

        response = self.client.post(
            reverse("plm:create_part", args=[self.project.id]),
            {
                "number": "",
                "name": "Naechstes Teil",
                "category": Part.Category.PART,
                "file": make_zip_upload(members={"Document.xml": "<Document />"}),
            },
        )

        part = Part.objects.get(name="Naechstes Teil")
        self.assertRedirects(response, reverse("plm:part_detail", args=[part.id]))
        self.assertEqual(part.number, "P-011")

    def test_reader_cannot_create_part(self):
        self.client.force_login(self.reader)

        response = self.client.post(
            reverse("plm:create_part", args=[self.project.id]),
            {
                "number": "P-002",
                "name": "Neues Teil",
                "category": Part.Category.PART,
                "file": make_zip_upload(),
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Part.objects.filter(number="P-002").exists())

    def test_duplicate_part_number_shows_error(self):
        self.client.force_login(self.editor)

        response = self.client.post(
            reverse("plm:create_part", args=[self.project.id]),
            {
                "number": "P-001",
                "name": "Doppelt",
                "category": Part.Category.PART,
                "file": make_zip_upload(),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "bereits", status_code=400)
        self.assertEqual(Part.objects.filter(number="P-001").count(), 1)

    def test_create_part_requires_initial_fcstd_file(self):
        self.client.force_login(self.editor)

        response = self.client.post(
            reverse("plm:create_part", args=[self.project.id]),
            {
                "number": "",
                "name": "Ohne Datei",
                "category": Part.Category.PART,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Part.objects.filter(name="Ohne Datei").exists())

    def test_part_detail_uses_properties_sidebar_and_fallback_page(self):
        self.client.force_login(self.reader)

        response = self.client.get(reverse("plm:part_detail", args=[self.part.id]))

        self.assertContains(response, 'class="properties-panel"')
        self.assertContains(response, "Eigenschaften anzeigen")
        self.assertContains(response, self.part.number)

        response = self.client.get(reverse("plm:part_properties", args=[self.part.id]))
        self.assertContains(response, "Eigenschaften")
        self.assertContains(response, self.part.number)

    def test_create_part_form_does_not_show_supplier(self):
        self.client.force_login(self.editor)

        response = self.client.get(reverse("plm:create_part", args=[self.project.id]))

        self.assertContains(response, "Neues Teil oder Baugruppe")
        self.assertNotContains(response, "Lieferant")

    def test_revision_properties_can_be_shown_in_sidebar_or_page(self):
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.editor)
        self.client.force_login(self.reader)

        response = self.client.get(
            reverse("plm:part_detail", args=[self.part.id]),
            {"properties_revision": revision.id},
        )

        self.assertContains(response, f"Revision {revision.revision_code}")
        self.assertContains(response, "Teileigenschaften anzeigen")

        response = self.client.get(reverse("plm:revision_properties", args=[revision.id]))
        self.assertContains(response, f"Revision {revision.revision_code}")
        self.assertContains(response, "Erstellungsdatum")
        self.assertContains(response, "Testteil aus FreeCAD")
        self.assertContains(response, "PLMRevision")
        self.assertNotContains(response, revision.sha256)
        self.assertNotContains(response, "FreeCAD-Version")


class ManufacturingFileTests(TestCase):
    def setUp(self):
        self.media_root = TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root.name)
        self.settings_override.enable()
        call_command("setup_plm_roles", stdout=StringIO())
        self.admin = get_user_model().objects.create_user(
            username="manufacturing-admin",
            password="test",
        )
        self.admin.groups.add(Group.objects.get(name=ROLE_ADMIN))
        self.editor = get_user_model().objects.create_user(
            username="manufacturing-editor",
            password="test",
        )
        self.editor.groups.add(Group.objects.get(name=ROLE_EDITOR))
        self.project = Project.objects.create(code="MFG", name="Fertigung")
        self.part = Part.objects.create(
            project=self.project,
            number="P-001",
            name="Druckteil",
        )
        self.revision = create_revision_from_upload(
            self.part,
            make_zip_upload(),
            self.admin,
        )

    def tearDown(self):
        self.settings_override.disable()
        self.media_root.cleanup()

    def test_service_creates_manufacturing_file_with_machine_context(self):
        machine = ManufacturingMachine.objects.create(
            name="Bambu X1C",
            manufacturer="Bambu Lab",
            model="X1 Carbon",
            integration_kind="bambulab",
        )

        manufacturing_file = create_manufacturing_file_from_upload(
            revision=self.revision,
            uploaded_file=make_3mf_upload(),
            uploaded_by=self.editor,
            label="PETG 0.20mm",
            slicer_name="Bambu Studio",
            machine=machine,
            material="PETG",
        )

        self.assertEqual(
            manufacturing_file.file_type,
            ManufacturingFile.FileType.SLICER_3MF,
        )
        self.assertEqual(manufacturing_file.machine, machine)
        self.assertEqual(manufacturing_file.status, ManufacturingFile.Status.APPROVED)
        self.assertEqual(manufacturing_file.metadata["container"], "3mf")
        self.assertTrue(manufacturing_file.metadata["has_thumbnail"])
        self.assertEqual(manufacturing_file.thumbnail_original_filename, "thumbnail.png")
        self.assertTrue(Path(manufacturing_file.thumbnail.path).exists())
        self.assertEqual(
            manufacturing_file.metadata["extracted_fields"]["printer_profile"],
            "0.20mm Standard @BBL X1C",
        )
        self.assertTrue(Path(manufacturing_file.file.path).exists())
        event = AuditEvent.objects.get(
            action=AuditEvent.Action.MANUFACTURING_FILE_UPLOADED
        )
        self.assertEqual(event.metadata["manufacturing_file_id"], manufacturing_file.id)

    def test_bambu_3mf_metadata_prefills_manufacturing_fields(self):
        manufacturing_file = create_manufacturing_file_from_upload(
            revision=self.revision,
            uploaded_file=make_3mf_upload(),
            uploaded_by=self.editor,
        )

        self.assertEqual(manufacturing_file.slicer_name, "Bambu Studio")
        self.assertEqual(manufacturing_file.machine_label, "Bambu Lab X1C")
        self.assertEqual(manufacturing_file.printer_profile, "0.20mm Standard @BBL X1C")
        self.assertEqual(manufacturing_file.material, "PETG")
        self.assertEqual(manufacturing_file.material_brand, "Bambu Lab")
        self.assertEqual(str(manufacturing_file.nozzle_diameter), "0.4")
        self.assertEqual(str(manufacturing_file.layer_height), "0.2")

    def test_bambu_json_3mf_metadata_prefills_manufacturing_fields(self):
        manufacturing_file = create_manufacturing_file_from_upload(
            revision=self.revision,
            uploaded_file=make_bambu_json_3mf_upload(),
            uploaded_by=self.editor,
        )

        self.assertEqual(manufacturing_file.slicer_name, "Bambu Studio")
        self.assertEqual(manufacturing_file.slicer_version, "02.07.01.57")
        self.assertEqual(manufacturing_file.machine_label, "Bambu Lab A1")
        self.assertEqual(manufacturing_file.printer_profile, "0.08mm Extra Fine @BBL A1")
        self.assertEqual(manufacturing_file.material, "PLA, ABS")
        self.assertEqual(manufacturing_file.material_brand, "SUNLU, Bambu Lab")
        self.assertEqual(str(manufacturing_file.nozzle_diameter), "0.4")
        self.assertEqual(str(manufacturing_file.layer_height), "0.08")

    def test_manual_manufacturing_fields_override_3mf_metadata(self):
        manufacturing_file = create_manufacturing_file_from_upload(
            revision=self.revision,
            uploaded_file=make_3mf_upload(),
            uploaded_by=self.editor,
            slicer_name="OrcaSlicer",
            machine_label="P1S",
            material="PLA",
        )

        self.assertEqual(manufacturing_file.slicer_name, "OrcaSlicer")
        self.assertEqual(manufacturing_file.machine_label, "P1S")
        self.assertEqual(manufacturing_file.material, "PLA")
        self.assertEqual(manufacturing_file.material_brand, "Bambu Lab")

    @override_settings(PLM_MAX_ZIP_MEMBERS=2)
    def test_service_rejects_3mf_with_too_many_zip_members(self):
        with self.assertRaises(ValidationError) as context:
            create_manufacturing_file_from_upload(
                revision=self.revision,
                uploaded_file=make_3mf_upload(),
                uploaded_by=self.editor,
            )

        self.assertIn("zu viele ZIP-Mitglieder", str(context.exception))

    def test_service_rejects_3mf_above_size_budget_without_size_attribute(self):
        data = make_3mf_upload().read()
        upload = UploadWithoutReportedSize("plate.3mf", data)

        with override_settings(PLM_MAX_PROJECT_ZIP_BYTES=len(data) - 1):
            with self.assertRaises(ValidationError) as context:
                create_manufacturing_file_from_upload(
                    revision=self.revision,
                    uploaded_file=upload,
                    uploaded_by=self.editor,
                )

        self.assertIn("Upload-Budget", str(context.exception))

    def test_duplicate_manufacturing_file_for_revision_is_rejected(self):
        content = make_3mf_upload().read()
        create_manufacturing_file_from_upload(
            revision=self.revision,
            uploaded_file=SimpleUploadedFile("first.3mf", content),
            uploaded_by=self.editor,
        )

        with self.assertRaises(ValidationError):
            create_manufacturing_file_from_upload(
                revision=self.revision,
                uploaded_file=SimpleUploadedFile("second.3mf", content),
                uploaded_by=self.editor,
            )

    def test_editor_can_upload_and_download_manufacturing_file(self):
        self.client.force_login(self.editor)

        response = self.client.post(
            reverse("plm:upload_manufacturing_file", args=[self.revision.id]),
            {
                "file": make_3mf_upload(),
                "file_type": ManufacturingFile.FileType.SLICER_3MF,
                "purpose": ManufacturingFile.Purpose.PRINT,
                "label": "Bambu PETG",
                "slicer_name": "Bambu Studio",
                "machine_label": "Bambu X1C",
                "material": "PETG",
            },
        )

        self.assertRedirects(response, reverse("plm:part_detail", args=[self.part.id]))
        manufacturing_file = ManufacturingFile.objects.get()
        self.assertEqual(manufacturing_file.status, ManufacturingFile.Status.APPROVED)

        detail = self.client.get(reverse("plm:part_detail", args=[self.part.id]))
        self.assertContains(detail, "Fertigung")
        self.assertContains(detail, "Bambu PETG")
        self.assertContains(detail, "Bambu Studio")
        self.assertContains(
            detail,
            reverse("plm:manufacturing_file_thumbnail", args=[manufacturing_file.id]),
        )

        download = self.client.get(
            reverse("plm:download_manufacturing_file", args=[manufacturing_file.id])
        )
        self.assertEqual(download.status_code, 200)
        self.assertEqual(
            download["Content-Disposition"],
            'attachment; filename="plate.3mf"',
        )
        download.close()
        thumbnail = self.client.get(
            reverse("plm:manufacturing_file_thumbnail", args=[manufacturing_file.id])
        )
        self.assertEqual(thumbnail.status_code, 200)
        self.assertEqual(
            thumbnail["Content-Disposition"],
            'inline; filename="thumbnail.png"',
        )
        thumbnail.close()

    def test_admin_can_mark_manufacturing_file_obsolete(self):
        manufacturing_file = create_manufacturing_file_from_upload(
            revision=self.revision,
            uploaded_file=make_3mf_upload(),
            uploaded_by=self.editor,
            status=ManufacturingFile.Status.APPROVED,
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("plm:obsolete_manufacturing_file", args=[manufacturing_file.id])
        )

        self.assertRedirects(response, reverse("plm:part_detail", args=[self.part.id]))
        manufacturing_file.refresh_from_db()
        self.assertEqual(manufacturing_file.status, ManufacturingFile.Status.OBSOLETE)
        self.assertTrue(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.MANUFACTURING_FILE_STATUS_CHANGED
            ).exists()
        )

    def test_project_delete_removes_manufacturing_files_and_run_attachments(self):
        machine = ManufacturingMachine.objects.create(name="Bambu X1C")
        manufacturing_file = create_manufacturing_file_from_upload(
            revision=self.revision,
            uploaded_file=make_3mf_upload(),
            uploaded_by=self.editor,
            machine=machine,
        )
        run = ManufacturingRun.objects.create(
            manufacturing_file=manufacturing_file,
            machine=machine,
            operator=self.admin,
        )
        attachment = ManufacturingRunAttachment.objects.create(
            run=run,
            attachment_type=ManufacturingRunAttachment.AttachmentType.PHOTO,
            file=ContentFile(b"\x89PNG\r\n\x1a\n", name="result.png"),
            original_filename="result.png",
            sha256="b" * 64,
            size_bytes=8,
            uploaded_by=self.admin,
        )
        manufacturing_path = Path(manufacturing_file.file.path)
        thumbnail_path = Path(manufacturing_file.thumbnail.path)
        attachment_path = Path(attachment.file.path)
        self.assertTrue(manufacturing_path.exists())
        self.assertTrue(thumbnail_path.exists())
        self.assertTrue(attachment_path.exists())
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("plm:delete_project", args=[self.project.id]),
            {"confirmation": "MFG"},
        )

        self.assertRedirects(response, reverse("plm:project_list"))
        self.assertFalse(ManufacturingFile.objects.exists())
        self.assertFalse(ManufacturingRun.objects.exists())
        self.assertFalse(ManufacturingRunAttachment.objects.exists())
        self.assertFalse(manufacturing_path.exists())
        self.assertFalse(thumbnail_path.exists())
        self.assertFalse(attachment_path.exists())


class ProjectDeleteTests(TestCase):
    def setUp(self):
        self.media_root = TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root.name)
        self.settings_override.enable()
        call_command("setup_plm_roles", stdout=StringIO())
        self.admin = get_user_model().objects.create_user(
            username="delete-admin",
            password="test",
        )
        self.admin.groups.add(Group.objects.get(name=ROLE_ADMIN))
        self.editor = get_user_model().objects.create_user(
            username="delete-editor",
            password="test",
        )
        self.editor.groups.add(Group.objects.get(name=ROLE_EDITOR))
        self.project = Project.objects.create(code="DEL", name="Loeschprojekt")
        self.part = Part.objects.create(
            project=self.project,
            number="P-001",
            name="Testteil",
        )

    def tearDown(self):
        self.settings_override.disable()
        self.media_root.cleanup()

    def create_project_content(self):
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.admin)
        artifact = RevisionArtifact.objects.create(
            revision=revision,
            artifact_type=RevisionArtifact.ArtifactType.PNG,
            view_name="front",
            file=ContentFile(b"\x89PNG\r\n\x1a\n", name="front.png"),
            original_filename="front.png",
            sha256="a" * 64,
            size_bytes=8,
        )
        snapshot = ProjectSnapshot.objects.create(
            project=self.project,
            name="Stand",
            created_by=self.admin,
        )
        ProjectSnapshotEntry.objects.create(
            snapshot=snapshot,
            path="Testteil.FCStd",
            revision=revision,
        )
        Checkout.objects.create(
            part=self.part,
            base_revision=revision,
            checked_out_by=self.admin,
        )
        Annotation.objects.create(
            project=self.project,
            part=self.part,
            revision=revision,
            text="Pruefen",
            created_by=self.admin,
        )
        return revision, artifact

    def test_admin_can_delete_project_with_contents_and_files(self):
        revision, artifact = self.create_project_content()
        revision_path = Path(revision.file.path)
        artifact_path = Path(artifact.file.path)
        self.assertTrue(revision_path.exists())
        self.assertTrue(artifact_path.exists())
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("plm:delete_project", args=[self.project.id]),
            {"confirmation": "DEL"},
        )

        self.assertRedirects(response, reverse("plm:project_list"))
        self.assertFalse(Project.objects.filter(id=self.project.id).exists())
        self.assertFalse(Part.objects.exists())
        self.assertFalse(Revision.objects.exists())
        self.assertFalse(RevisionArtifact.objects.exists())
        self.assertFalse(ProjectSnapshot.objects.exists())
        self.assertFalse(Checkout.objects.exists())
        self.assertFalse(Annotation.objects.exists())
        self.assertFalse(revision_path.exists())
        self.assertFalse(artifact_path.exists())
        event = AuditEvent.objects.get(action=AuditEvent.Action.PROJECT_DELETED)
        self.assertEqual(event.metadata["project_code"], "DEL")
        self.assertEqual(event.metadata["parts"], 1)

    def test_project_delete_requires_exact_code(self):
        self.create_project_content()
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("plm:delete_project", args=[self.project.id]),
            {"confirmation": "WRONG"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(Project.objects.filter(id=self.project.id).exists())
        self.assertTrue(Revision.objects.exists())

    def test_editor_cannot_delete_project(self):
        self.client.force_login(self.editor)

        response = self.client.post(
            reverse("plm:delete_project", args=[self.project.id]),
            {"confirmation": "DEL"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Project.objects.filter(id=self.project.id).exists())


class FreeCADCmdJobTests(TestCase):
    def setUp(self):
        self.media_root = TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root.name)
        self.settings_override.enable()
        self.user = get_user_model().objects.create_user(
            username="editor",
            password="test",
        )
        self.project = Project.objects.create(code="PRJ", name="Projekt")
        self.part = Part.objects.create(
            project=self.project,
            number="P-001",
            name="Testteil",
        )
        self.revision = create_revision_from_upload(
            self.part,
            make_zip_upload(),
            self.user,
        )

    def tearDown(self):
        self.settings_override.disable()
        self.media_root.cleanup()

    def fake_freecadcmd(self, result_code):
        script = Path(self.media_root.name) / "fake_freecadcmd.py"
        script.write_text(
            f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

spec = json.loads(Path(sys.argv[-2]).read_text())
output_dir = Path(spec["output_dir"])
artifact_path = output_dir / "artifact.step"
artifact_path.write_bytes(b"STEP DATA")
result = {{
    "metadata": {{
        "objects": [
            {{"name": "Body", "label": "Gehaeuse", "type": "PartDesign::Body", "visible": True, "exportable": True}}
        ],
        "varsets": [
            {{"name": "Parameters", "label": "Parameters", "properties": [
                {{"name": "Width", "type": "App::PropertyFloat", "value": "42.0"}}
            ]}}
        ],
    }},
    "artifacts": {json.dumps(result_code)},
}}
Path(sys.argv[-1]).write_text(json.dumps(result))
""",
            encoding="utf-8",
        )
        script.chmod(0o755)
        return str(script)

    def fake_preview_freecadcmd(self, required_files=None):
        required_files = required_files or []
        script = Path(self.media_root.name) / "fake_preview_freecadcmd.py"
        script.write_text(
            """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

spec = json.loads(Path(sys.argv[-2]).read_text())
output_dir = Path(spec["output_dir"])
workdir = Path(spec["fcstd_path"]).parent
missing = [name for name in __REQUIRED_FILES__ if not (workdir / name).exists()]
if missing:
    raise SystemExit("Missing staged files: " + ", ".join(missing))
step_path = output_dir / "preview.step"
stl_path = output_dir / "preview.stl"
step_path.write_bytes(b"STEP DATA")
stl_path.write_text(
    "solid triangle\\n"
    "facet normal 0 0 1\\n"
    "outer loop\\n"
    "vertex 0 0 0\\n"
    "vertex 10 0 0\\n"
    "vertex 0 10 0\\n"
    "endloop\\n"
    "endfacet\\n"
    "endsolid triangle\\n"
)
result = {
    "metadata": {"objects": [], "varsets": []},
    "preview_mesh_path": str(stl_path),
    "artifacts": [
        {"path": str(step_path), "artifact_type": "step", "view_name": "preview"}
    ],
}
Path(sys.argv[-1]).write_text(json.dumps(result))
""".replace("__REQUIRED_FILES__", json.dumps(required_files)),
            encoding="utf-8",
        )
        script.chmod(0o755)
        return str(script)

    def test_inspect_job_stores_freecadcmd_metadata(self):
        executable = self.fake_freecadcmd([])
        job = create_export_job(
            revision=self.revision,
            job_type=ExportJob.JobType.INSPECT,
            created_by=self.user,
        )

        with override_settings(FREECADCMD_COMMAND=executable):
            process_export_job(job)

        job.refresh_from_db()
        self.revision.refresh_from_db()
        self.assertEqual(job.status, ExportJob.Status.SUCCEEDED)
        self.assertEqual(
            self.revision.extracted_metadata["freecadcmd"]["objects"][0]["name"],
            "Body",
        )
        self.assertEqual(
            self.revision.extracted_metadata["freecadcmd"]["varsets"][0]["properties"][0]["name"],
            "Width",
        )

    def test_export_job_creates_revision_artifact(self):
        executable = self.fake_freecadcmd(
            [{"path": "", "artifact_type": "step", "view_name": ""}]
        )
        # The fake writes artifact.step; point the result at that file at runtime.
        script = Path(executable)
        text = script.read_text()
        text = text.replace('"path": ""', '"path": str(artifact_path)')
        script.write_text(text)
        job = create_export_job(
            revision=self.revision,
            job_type=ExportJob.JobType.EXPORT,
            export_format=ExportJob.ExportFormat.STEP,
            selected_objects=["Body"],
            created_by=self.user,
        )

        with override_settings(FREECADCMD_COMMAND=executable):
            process_export_job(job)

        job.refresh_from_db()
        artifact = RevisionArtifact.objects.get()
        self.assertEqual(job.status, ExportJob.Status.SUCCEEDED)
        self.assertEqual(artifact.artifact_type, RevisionArtifact.ArtifactType.STEP)
        self.assertEqual(artifact.size_bytes, len(b"STEP DATA"))

    def test_png_job_renders_preview_mesh_without_freecad_gui(self):
        executable = self.fake_preview_freecadcmd()
        job = create_export_job(
            revision=self.revision,
            job_type=ExportJob.JobType.PNG_VIEWS,
            created_by=self.user,
        )

        with override_settings(FREECADCMD_COMMAND=executable):
            process_export_job(job)

        job.refresh_from_db()
        self.assertEqual(job.status, ExportJob.Status.SUCCEEDED)
        self.assertEqual(
            RevisionArtifact.objects.filter(
                artifact_type=RevisionArtifact.ArtifactType.STEP,
                view_name="preview",
            ).count(),
            1,
        )
        self.assertEqual(
            RevisionArtifact.objects.filter(
                artifact_type=RevisionArtifact.ArtifactType.STL,
                view_name="viewer-preview",
            ).count(),
            1,
        )
        self.assertEqual(
            RevisionArtifact.objects.filter(
                artifact_type=RevisionArtifact.ArtifactType.PNG,
            ).count(),
            7,
        )

    def test_png_job_stages_referenced_project_files_for_freecadcmd(self):
        snapshot = import_project_snapshot(
            self.project,
            make_project_zip_upload(),
            self.user,
            name="Arbeitsstand",
        )
        revision = snapshot.entries.get(path="Druck.FCStd").revision
        executable = self.fake_preview_freecadcmd(
            ["Box.FCStd", "Deckel.FCStd", "Chip.FCStd"]
        )
        job = create_export_job(
            revision=revision,
            job_type=ExportJob.JobType.PNG_VIEWS,
            created_by=self.user,
        )

        with override_settings(FREECADCMD_COMMAND=executable):
            process_export_job(job)

        job.refresh_from_db()
        self.assertEqual(job.status, ExportJob.Status.SUCCEEDED)
        self.assertEqual(
            RevisionArtifact.objects.filter(
                job=job,
                artifact_type=RevisionArtifact.ArtifactType.PNG,
            ).count(),
            7,
        )

    def test_missing_freecadcmd_marks_job_failed(self):
        job = create_export_job(
            revision=self.revision,
            job_type=ExportJob.JobType.INSPECT,
            created_by=self.user,
        )

        with override_settings(FREECADCMD_COMMAND="/missing/FreeCADCmd"):
            process_export_job(job)

        job.refresh_from_db()
        self.assertEqual(job.status, ExportJob.Status.FAILED)
        self.assertIn("FreeCADCmd wurde nicht gefunden", job.error)

    def test_flatpak_command_gets_tmp_access_for_worker_files(self):
        command = with_flatpak_worker_options(
            [
                "flatpak",
                "run",
                "--branch=stable",
                "--command=FreeCADCmd",
                "org.freecad.FreeCAD",
            ]
        )

        self.assertIn("--filesystem=/tmp", command)
        self.assertLess(command.index("--filesystem=/tmp"), command.index("org.freecad.FreeCAD"))

    def test_png_default_flatpak_fallback_stays_headless(self):
        job = create_export_job(
            revision=self.revision,
            job_type=ExportJob.JobType.PNG_VIEWS,
            created_by=self.user,
        )

        with (
            patch("plm.freecadcmd.shutil.which") as which,
            override_settings(FREECADCMD_COMMAND="FreeCADCmd"),
        ):
            which.side_effect = lambda name: "/usr/bin/flatpak" if name == "flatpak" else None
            command = freecadcmd_command(job)

        self.assertIn("--command=FreeCADCmd", command)
        self.assertNotIn("--command=FreeCAD", command)

    def test_mesh_preview_renderer_creates_png_views(self):
        stl_path = Path(self.media_root.name) / "triangle.stl"
        output_dir = Path(self.media_root.name) / "preview"
        output_dir.mkdir()
        stl_path.write_text(
            """solid triangle
facet normal 0 0 1
outer loop
vertex 0 0 0
vertex 10 0 0
vertex 0 10 0
endloop
endfacet
endsolid triangle
""",
            encoding="utf-8",
        )

        artifacts = render_stl_views(stl_path, output_dir, "R0001", width=80, height=60)

        self.assertEqual(len(artifacts), 7)
        for artifact in artifacts:
            path = Path(artifact["path"])
            self.assertEqual(artifact["artifact_type"], "png")
            self.assertTrue(path.exists())
            self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_reader_cannot_create_export_job(self):
        reader = get_user_model().objects.create_user(
            username="reader-job",
            password="test",
        )
        call_command("setup_plm_roles", stdout=StringIO())
        reader.groups.add(Group.objects.get(name=ROLE_READER))
        self.client.force_login(reader)

        response = self.client.post(
            reverse("plm:create_revision_inspect_job", args=[self.revision.id])
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ExportJob.objects.exists())


class AddonApiWorkflowTests(TestCase):
    def setUp(self):
        self.media_root = TemporaryDirectory()
        self.settings_override = override_settings(
            MEDIA_ROOT=self.media_root.name,
            ALLOWED_HOSTS=["testserver"],
        )
        self.settings_override.enable()
        call_command("setup_plm_roles", stdout=StringIO())

        self.user = get_user_model().objects.create_user(
            username="addon-user",
            password="test",
            is_superuser=True,
        )
        self.project = Project.objects.create(code="PRJ", name="Projekt")
        self.part = Part.objects.create(
            project=self.project,
            number="P-001",
            name="Testteil",
        )

    def tearDown(self):
        self.settings_override.disable()
        self.media_root.cleanup()

    def authorize_token(self, scopes=None, user=None):
        token, raw_token = create_api_token(
            user=user or self.user,
            name="FreeCAD Addon",
            scopes=scopes or [ApiToken.Scope.READ],
        )
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {raw_token}"
        return token, raw_token

    def post_json(self, url, payload):
        return self.client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
        )

    def test_api_lists_projects_and_creates_parts(self):
        self.authorize_token([ApiToken.Scope.READ, ApiToken.Scope.WRITE])

        response = self.client.get(reverse("plm:api_projects"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["projects"][0]["code"], "PRJ")

        response = self.post_json(
            reverse("plm:api_project_parts", args=[self.project.id]),
            {
                "number": "P-002",
                "name": "Addon-Teil",
                "category": Part.Category.PART,
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["part"]["number"], "P-002")
        self.assertTrue(Part.objects.filter(number="P-002").exists())

    def test_api_admin_token_can_update_project_metadata(self):
        self.authorize_token([ApiToken.Scope.ADMIN])

        response = self.post_json(
            reverse("plm:api_project", args=[self.project.id]),
            {
                "code": " neu ",
                "name": " Aktualisiert ",
                "status": Project.Status.ORDER,
                "project_date": "2026-07-08",
                "description": " Via Addon ",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.code, "NEU")
        self.assertEqual(self.project.name, "Aktualisiert")
        self.assertEqual(self.project.status, Project.Status.ORDER)
        self.assertEqual(self.project.project_date.isoformat(), "2026-07-08")
        self.assertEqual(self.project.description, "Via Addon")
        self.assertTrue(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.PROJECT_UPDATED,
                metadata__project_id=self.project.id,
            ).exists()
        )

    def test_api_imports_project_snapshot_into_existing_project(self):
        self.authorize_token([ApiToken.Scope.WRITE])

        response = self.client.post(
            reverse("plm:api_project_snapshot_import", args=[self.project.id]),
            {
                "name": "Arbeitsstand",
                "file": make_project_zip_upload(
                    members={
                        "Box.FCStd": make_fcstd_bytes("Box"),
                        "Assembly.FCStd": make_fcstd_bytes(
                            "Assembly",
                            object_type="Assembly::AssemblyObject",
                            xlinks=[("Box.FCStd", "Body")],
                        ),
                    }
                ),
            },
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["project"]["id"], self.project.id)
        self.assertEqual(payload["snapshot"]["name"], "Arbeitsstand")
        self.assertEqual(payload["import_summary"]["created_parts"], 2)
        self.assertEqual(payload["import_summary"]["created_revisions"], 2)
        self.assertEqual(
            sorted(entry["path"] for entry in payload["snapshot"]["entries"]),
            ["Assembly.FCStd", "Box.FCStd"],
        )
        self.assertTrue(
            Part.objects.filter(
                project=self.project,
                name="Assembly",
                category=Part.Category.ASSEMBLY,
            ).exists()
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.PROJECT_SNAPSHOT_CREATED,
                metadata__project_id=self.project.id,
            ).exists()
        )

    def test_api_creates_project_and_imports_snapshot(self):
        self.authorize_token([ApiToken.Scope.ADMIN])

        response = self.client.post(
            reverse("plm:api_project_import"),
            {
                "code": " imp ",
                "name": "Importprojekt",
                "status": Project.Status.ORDER,
                "project_date": "2026-07-08",
                "description": "Via Addon",
                "snapshot_name": "Initial",
                "file": make_project_zip_upload(
                    members={
                        "parts/Box.FCStd": make_fcstd_bytes("Box", freecad_id="BOX-001"),
                        "Assembly.FCStd": make_fcstd_bytes(
                            "Assembly",
                            object_type="Assembly::AssemblyObject",
                            xlinks=[("parts/Box.FCStd", "Body")],
                        ),
                    }
                ),
            },
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        project = Project.objects.get(code="IMP")
        self.assertEqual(project.name, "Importprojekt")
        self.assertEqual(project.status, Project.Status.ORDER)
        self.assertEqual(project.project_date.isoformat(), "2026-07-08")
        self.assertEqual(project.description, "Via Addon")
        self.assertEqual(payload["project"]["id"], project.id)
        self.assertEqual(payload["snapshot"]["name"], "Initial")
        self.assertEqual(
            sorted(entry["path"] for entry in payload["snapshot"]["entries"]),
            ["Assembly.FCStd", "parts/Box.FCStd"],
        )
        self.assertTrue(project.parts.filter(number="BOX-001").exists())

    def test_api_snapshot_import_requires_write_scope(self):
        self.authorize_token([ApiToken.Scope.READ])

        response = self.client.post(
            reverse("plm:api_project_snapshot_import", args=[self.project.id]),
            {"name": "Arbeitsstand", "file": make_project_zip_upload()},
        )

        self.assertEqual(response.status_code, 403)

    def test_api_rejects_missing_authentication(self):
        response = self.client.get(reverse("plm:api_projects"))

        self.assertEqual(response.status_code, 401)

    def test_api_rejects_browser_session_without_token(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("plm:api_projects"))

        self.assertEqual(response.status_code, 401)

    def test_read_token_lists_projects_and_updates_last_used(self):
        token, raw_token = self.authorize_token([ApiToken.Scope.READ])

        response = self.client.get(reverse("plm:api_projects"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["projects"][0]["code"], "PRJ")
        token.refresh_from_db()
        self.assertIsNotNone(token.last_used_at)
        self.assertNotEqual(token.token_hash, raw_token)
        self.assertTrue(token.token_hash)

    def test_read_token_cannot_create_part(self):
        self.authorize_token([ApiToken.Scope.READ])

        response = self.post_json(
            reverse("plm:api_project_parts", args=[self.project.id]),
            {
                "number": "P-002",
                "name": "Nicht erlaubt",
                "category": Part.Category.PART,
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Part.objects.filter(number="P-002").exists())

    def test_write_token_can_create_part_when_user_role_allows_it(self):
        self.authorize_token([ApiToken.Scope.WRITE])

        response = self.post_json(
            reverse("plm:api_project_parts", args=[self.project.id]),
            {
                "number": "P-002",
                "name": "Token-Teil",
                "category": Part.Category.PART,
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(Part.objects.filter(number="P-002").exists())

    def test_write_token_still_respects_django_roles(self):
        reader = get_user_model().objects.create_user(username="api-reader")
        reader.groups.add(Group.objects.get(name=ROLE_READER))
        self.authorize_token([ApiToken.Scope.WRITE], user=reader)

        response = self.post_json(
            reverse("plm:api_project_parts", args=[self.project.id]),
            {
                "number": "P-002",
                "name": "Nicht erlaubt",
                "category": Part.Category.PART,
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Part.objects.filter(number="P-002").exists())

    def test_revoked_token_is_rejected(self):
        token, _raw_token = self.authorize_token([ApiToken.Scope.READ])
        token.revoked_at = timezone.now()
        token.save(update_fields=["revoked_at", "updated_at"])

        response = self.client.get(reverse("plm:api_projects"))

        self.assertEqual(response.status_code, 401)

    def test_unknown_token_is_rejected(self):
        self.client.defaults["HTTP_AUTHORIZATION"] = "Bearer plm_pat_unknown"

        response = self.client.get(reverse("plm:api_projects"))

        self.assertEqual(response.status_code, 401)

    def test_expired_token_is_rejected(self):
        self.authorize_token([ApiToken.Scope.READ])
        token = ApiToken.objects.get()
        token.expires_at = timezone.now() - timedelta(minutes=1)
        token.save(update_fields=["expires_at", "updated_at"])

        response = self.client.get(reverse("plm:api_projects"))

        self.assertEqual(response.status_code, 401)

    def test_checkout_manifest_contains_snapshot_exact_dependencies(self):
        self.authorize_token([ApiToken.Scope.READ, ApiToken.Scope.CHECKOUT])
        snapshot = import_project_snapshot(
            self.project,
            make_project_zip_upload(),
            self.user,
            name="Arbeitsstand",
        )
        root_revision = Revision.objects.get(part__name="Druck")

        response = self.post_json(
            reverse("plm:api_revision_checkout", args=[root_revision.id]),
            {"snapshot_id": snapshot.id, "workspace_hint": "~/FreeCAD-PLM/PRJ"},
        )

        self.assertEqual(response.status_code, 201)
        manifest = response.json()["manifest"]
        self.assertEqual(manifest["snapshot"]["id"], snapshot.id)
        self.assertEqual(manifest["part"]["number"], "A-001")
        self.assertEqual(
            sorted(item["path"] for item in manifest["files"]),
            ["Box.FCStd", "Chip.FCStd", "Deckel.FCStd", "Druck.FCStd"],
        )
        self.assertEqual(Checkout.objects.get().status, Checkout.Status.ACTIVE)

    def test_checkout_rejects_snapshot_from_different_project(self):
        self.authorize_token([ApiToken.Scope.READ, ApiToken.Scope.CHECKOUT])
        other_project = Project.objects.create(code="OTHER", name="Anderes Projekt")
        foreign_snapshot = import_project_snapshot(
            other_project,
            make_project_zip_upload("foreign.zip"),
            self.user,
            name="Fremdstand",
        )
        root_revision = create_revision_from_upload(
            self.part,
            make_zip_upload(),
            self.user,
        )

        response = self.post_json(
            reverse("plm:api_revision_checkout", args=[root_revision.id]),
            {"snapshot_id": foreign_snapshot.id},
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Checkout.objects.exists())

    def test_read_token_fetches_single_revision_manifest_without_checkout(self):
        self.authorize_token([ApiToken.Scope.READ])
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)

        response = self.client.get(
            reverse("plm:api_revision_manifest", args=[revision.id])
        )

        self.assertEqual(response.status_code, 200)
        expected_download_url = (
            f"http://testserver{reverse('plm:api_revision_file', args=[revision.id])}"
        )
        manifest = response.json()["manifest"]
        self.assertEqual(manifest["part"]["number"], "P-001")
        self.assertEqual(manifest["revision"]["id"], revision.id)
        self.assertEqual(manifest["revision"]["download_url"], expected_download_url)
        self.assertIsNone(manifest["snapshot"])
        self.assertEqual(len(manifest["files"]), 1)
        self.assertEqual(
            manifest["files"][0],
            {
                "path": "part.FCStd",
                "is_root": True,
                "revision_id": revision.id,
                "part_id": self.part.id,
                "part_number": "P-001",
                "revision_code": "R0001",
                "filename": "part.FCStd",
                "sha256": revision.sha256,
                "size_bytes": revision.size_bytes,
                "download_url": expected_download_url,
            },
        )
        self.assertFalse(Checkout.objects.exists())

    def test_revision_manifest_with_snapshot_contains_exact_dependencies(self):
        self.authorize_token([ApiToken.Scope.READ])
        snapshot = import_project_snapshot(
            self.project,
            make_project_zip_upload(),
            self.user,
            name="Arbeitsstand",
        )
        root_revision = Revision.objects.get(part__name="Druck")

        response = self.client.get(
            reverse("plm:api_revision_manifest", args=[root_revision.id]),
            {"snapshot_id": snapshot.id},
        )

        self.assertEqual(response.status_code, 200)
        manifest = response.json()["manifest"]
        self.assertEqual(manifest["snapshot"]["id"], snapshot.id)
        self.assertEqual(manifest["revision"]["id"], root_revision.id)
        self.assertEqual(
            sorted(item["path"] for item in manifest["files"]),
            ["Box.FCStd", "Chip.FCStd", "Deckel.FCStd", "Druck.FCStd"],
        )
        self.assertEqual(
            [item["path"] for item in manifest["files"] if item["is_root"]],
            ["Druck.FCStd"],
        )
        self.assertTrue(all(item["download_url"] for item in manifest["files"]))
        self.assertFalse(Checkout.objects.exists())

    def test_revision_manifest_rejects_referenced_revision_without_snapshot(self):
        self.authorize_token([ApiToken.Scope.READ])
        revision = create_revision_from_upload(
            self.part,
            make_zip_upload(
                members={
                    "Document.xml": freecad_document_xml(
                        "Druck",
                        xlinks=[("Box.FCStd", "Body")],
                    ),
                }
            ),
            self.user,
            normalize_plm_revision=True,
        )

        response = self.client.get(
            reverse("plm:api_revision_manifest", args=[revision.id])
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["error"],
            "Referenzierte Revisionen koennen nur mit Projektstand geladen werden.",
        )
        self.assertFalse(Checkout.objects.exists())

    def test_checkout_token_lists_only_own_active_checkouts(self):
        other_user = get_user_model().objects.create_user(username="other-addon-user")
        active_revision = create_revision_from_upload(
            self.part,
            make_zip_upload("active.FCStd"),
            self.user,
        )
        active_checkout = create_checkout(
            base_revision=active_revision,
            checked_out_by=self.user,
            workspace_hint="/home/ralf/FreeCAD-PLM",
        )
        other_part = Part.objects.create(
            project=self.project,
            number="P-002",
            name="Fremdes Teil",
        )
        other_revision = create_revision_from_upload(
            other_part,
            make_zip_upload("other.FCStd"),
            self.user,
        )
        other_checkout = create_checkout(
            base_revision=other_revision,
            checked_out_by=other_user,
        )
        completed_part = Part.objects.create(
            project=self.project,
            number="P-003",
            name="Eingechecktes Teil",
        )
        completed_revision = create_revision_from_upload(
            completed_part,
            make_zip_upload("completed.FCStd"),
            self.user,
        )
        completed_checkout = create_checkout(
            base_revision=completed_revision,
            checked_out_by=self.user,
        )
        completed_checkout.status = Checkout.Status.COMPLETED
        completed_checkout.completed_at = timezone.now()
        completed_checkout.save(update_fields=["status", "completed_at", "updated_at"])
        canceled_part = Part.objects.create(
            project=self.project,
            number="P-004",
            name="Abgebrochenes Teil",
        )
        canceled_revision = create_revision_from_upload(
            canceled_part,
            make_zip_upload("canceled.FCStd"),
            self.user,
        )
        canceled_checkout = create_checkout(
            base_revision=canceled_revision,
            checked_out_by=self.user,
        )
        canceled_checkout.status = Checkout.Status.CANCELED
        canceled_checkout.canceled_at = timezone.now()
        canceled_checkout.save(update_fields=["status", "canceled_at", "updated_at"])
        self.authorize_token([ApiToken.Scope.CHECKOUT])

        response = self.client.get(reverse("plm:api_active_checkouts"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["checkouts"]), 1)
        checkout = payload["checkouts"][0]
        self.assertEqual(checkout["id"], active_checkout.id)
        self.assertEqual(checkout["status"], Checkout.Status.ACTIVE)
        self.assertEqual(checkout["workspace_hint"], "/home/ralf/FreeCAD-PLM")
        self.assertEqual(checkout["project"]["code"], "PRJ")
        self.assertEqual(checkout["part"]["number"], "P-001")
        self.assertEqual(checkout["revision"]["id"], active_revision.id)
        self.assertEqual(
            checkout["manifest_url"],
            reverse("plm:api_checkout_manifest", args=[active_checkout.id]),
        )
        self.assertNotEqual(checkout["id"], other_checkout.id)
        self.assertNotEqual(checkout["id"], completed_checkout.id)
        self.assertNotEqual(checkout["id"], canceled_checkout.id)

    def test_read_token_cannot_list_active_checkouts(self):
        self.authorize_token([ApiToken.Scope.READ])

        response = self.client.get(reverse("plm:api_active_checkouts"))

        self.assertEqual(response.status_code, 403)

    def test_active_checkout_manifest_url_can_be_loaded(self):
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)
        checkout = create_checkout(
            base_revision=revision,
            checked_out_by=self.user,
        )
        self.authorize_token([ApiToken.Scope.READ, ApiToken.Scope.CHECKOUT])

        active_response = self.client.get(reverse("plm:api_active_checkouts"))
        manifest_url = active_response.json()["checkouts"][0]["manifest_url"]
        manifest_response = self.client.get(manifest_url)

        self.assertEqual(manifest_response.status_code, 200)
        self.assertEqual(manifest_response.json()["checkout"]["id"], checkout.id)
        self.assertEqual(
            manifest_response.json()["manifest"]["files"][0]["is_root"],
            True,
        )

    def test_second_active_checkout_for_same_part_is_rejected(self):
        self.authorize_token([ApiToken.Scope.CHECKOUT])
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)
        url = reverse("plm:api_revision_checkout", args=[revision.id])

        first = self.post_json(url, {})
        second = self.post_json(url, {})

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(Checkout.objects.count(), 1)

    def test_checkin_creates_new_revision_and_completes_checkout(self):
        self.authorize_token([ApiToken.Scope.CHECKOUT])
        create_revision_from_upload(self.part, make_zip_upload(), self.user)
        base_revision = Revision.objects.get(revision_code="R0001")
        checkout_response = self.post_json(
            reverse("plm:api_revision_checkout", args=[base_revision.id]),
            {},
        )
        checkout_id = checkout_response.json()["checkout"]["id"]
        updated_data = fcstd_with_plm_revision(
            make_fcstd_bytes("Updated Part"),
            "R0002",
        )

        response = self.client.post(
            reverse("plm:api_checkout_checkin", args=[checkout_id]),
            {
                "file": SimpleUploadedFile("updated.FCStd", updated_data),
                "change_summary": "Geometrie angepasst.",
            },
        )

        self.assertEqual(response.status_code, 201)
        checkout = Checkout.objects.get(id=checkout_id)
        revision = Revision.objects.get(revision_code="R0002")
        self.assertEqual(checkout.status, Checkout.Status.COMPLETED)
        self.assertEqual(checkout.completed_revision, revision)
        self.assertEqual(revision.notes, "Geometrie angepasst.")

    def test_checkin_ignores_technical_only_single_file_change(self):
        self.authorize_token([ApiToken.Scope.CHECKOUT])
        create_revision_from_upload(self.part, make_zip_upload(), self.user)
        base_revision = Revision.objects.get(revision_code="R0001")
        checkout_response = self.post_json(
            reverse("plm:api_revision_checkout", args=[base_revision.id]),
            {},
        )
        checkout_id = checkout_response.json()["checkout"]["id"]
        noisy_data = noisy_fcstd_bytes(make_zip_upload().read(), plm_revision="R0002")

        response = self.client.post(
            reverse("plm:api_checkout_checkin", args=[checkout_id]),
            {
                "file": SimpleUploadedFile("updated.FCStd", noisy_data),
                "change_summary": "Nur gespeichert.",
            },
        )

        self.assertEqual(response.status_code, 200)
        checkout = Checkout.objects.get(id=checkout_id)
        self.assertEqual(checkout.status, Checkout.Status.ACTIVE)
        self.assertIsNone(checkout.completed_revision)
        self.assertEqual(Revision.objects.count(), 1)
        payload = response.json()
        self.assertIsNone(payload["revision"])
        self.assertEqual(payload["revisions"], [])
        self.assertEqual(
            payload["ignored_files"],
            [{"path": "part.FCStd", "reason": "no_model_change"}],
        )

    def test_multi_file_checkin_can_update_referenced_file_only(self):
        self.authorize_token([ApiToken.Scope.READ, ApiToken.Scope.CHECKOUT])
        snapshot = import_project_snapshot(
            self.project,
            make_project_zip_upload(),
            self.user,
            name="Arbeitsstand",
        )
        root_revision = Revision.objects.get(part__name="Druck")
        box_revision = Revision.objects.get(part__name="Box")
        checkout_response = self.post_json(
            reverse("plm:api_revision_checkout", args=[root_revision.id]),
            {"snapshot_id": snapshot.id},
        )
        checkout_id = checkout_response.json()["checkout"]["id"]
        updated_box = fcstd_with_plm_revision(
            make_fcstd_bytes("Box geaendert", xlinks=[("Chip.FCStd", "VarSet")]),
            "R0002",
        )
        metadata = [
            {
                "field": "file_0",
                "path": "Box.FCStd",
                "revision_id": box_revision.id,
                "base_sha256": box_revision.sha256,
                "sha256": sha256(updated_box).hexdigest(),
                "is_root": False,
            }
        ]

        response = self.client.post(
            reverse("plm:api_checkout_checkin", args=[checkout_id]),
            {
                "files_metadata": json.dumps(metadata),
                "file_0": SimpleUploadedFile("Box.FCStd", updated_box),
                "change_summary": "Box angepasst.",
            },
        )

        self.assertEqual(response.status_code, 201)
        checkout = Checkout.objects.get(id=checkout_id)
        self.assertEqual(checkout.status, Checkout.Status.COMPLETED)
        self.assertIsNone(checkout.completed_revision)
        payload = response.json()
        self.assertIsNone(payload["revision"])
        self.assertEqual(payload["revisions"][0]["path"], "Box.FCStd")
        created_revision = Revision.objects.get(id=payload["revisions"][0]["revision"]["id"])
        self.assertEqual(created_revision.part.name, "Box")
        self.assertEqual(created_revision.revision_code, "R0002")
        self.assertEqual(created_revision.notes, "Box angepasst.")

    def test_multi_file_checkin_can_update_root_and_referenced_file(self):
        self.authorize_token([ApiToken.Scope.READ, ApiToken.Scope.CHECKOUT])
        snapshot = import_project_snapshot(
            self.project,
            make_project_zip_upload(),
            self.user,
            name="Arbeitsstand",
        )
        root_revision = Revision.objects.get(part__name="Druck")
        box_revision = Revision.objects.get(part__name="Box")
        checkout_response = self.post_json(
            reverse("plm:api_revision_checkout", args=[root_revision.id]),
            {"snapshot_id": snapshot.id},
        )
        checkout_id = checkout_response.json()["checkout"]["id"]
        updated_root = fcstd_with_plm_revision(
            make_fcstd_bytes(
                "Druck geaendert",
                object_type="Assembly::AssemblyObject",
                xlinks=[("Box.FCStd", "Body"), ("Deckel.FCStd", "Body")],
            ),
            "R0002",
        )
        updated_box = fcstd_with_plm_revision(
            make_fcstd_bytes("Box geaendert", xlinks=[("Chip.FCStd", "VarSet")]),
            "R0002",
        )
        metadata = [
            {
                "field": "file_0",
                "path": "Druck.FCStd",
                "revision_id": root_revision.id,
                "base_sha256": root_revision.sha256,
                "sha256": sha256(updated_root).hexdigest(),
                "is_root": True,
            },
            {
                "field": "file_1",
                "path": "Box.FCStd",
                "revision_id": box_revision.id,
                "base_sha256": box_revision.sha256,
                "sha256": sha256(updated_box).hexdigest(),
                "is_root": False,
            },
        ]

        response = self.client.post(
            reverse("plm:api_checkout_checkin", args=[checkout_id]),
            {
                "files_metadata": json.dumps(metadata),
                "file_0": SimpleUploadedFile("Druck.FCStd", updated_root),
                "file_1": SimpleUploadedFile("Box.FCStd", updated_box),
                "change_summary": "Baugruppe und Box angepasst.",
            },
        )

        self.assertEqual(response.status_code, 201)
        checkout = Checkout.objects.get(id=checkout_id)
        self.assertEqual(checkout.status, Checkout.Status.COMPLETED)
        payload = response.json()
        self.assertEqual(payload["revision"]["revision_code"], "R0002")
        self.assertEqual(
            [item["path"] for item in payload["revisions"]],
            ["Druck.FCStd", "Box.FCStd"],
        )
        root_created = Revision.objects.get(id=payload["revision"]["id"])
        self.assertEqual(checkout.completed_revision, root_created)
        self.assertEqual(root_created.part.name, "Druck")
        self.assertTrue(
            Revision.objects.filter(part=box_revision.part, revision_code="R0002").exists()
        )
        new_snapshot = ProjectSnapshot.objects.exclude(id=snapshot.id).get()
        self.assertEqual(
            new_snapshot.entries.get(path="Druck.FCStd").revision,
            root_created,
        )

        next_checkout = self.post_json(
            reverse("plm:api_revision_checkout", args=[root_created.id]),
            {},
        )

        self.assertEqual(next_checkout.status_code, 201)
        self.assertEqual(
            next_checkout.json()["manifest"]["snapshot"]["id"],
            new_snapshot.id,
        )

    def test_multi_file_checkin_ignores_technical_only_files_and_keeps_real_changes(self):
        self.authorize_token([ApiToken.Scope.READ, ApiToken.Scope.CHECKOUT])
        snapshot = import_project_snapshot(
            self.project,
            make_project_zip_upload(),
            self.user,
            name="Arbeitsstand",
        )
        root_revision = Revision.objects.get(part__name="Druck")
        box_revision = Revision.objects.get(part__name="Box")
        deckel_revision = Revision.objects.get(part__name="Deckel")
        checkout_response = self.post_json(
            reverse("plm:api_revision_checkout", args=[root_revision.id]),
            {"snapshot_id": snapshot.id},
        )
        checkout_id = checkout_response.json()["checkout"]["id"]
        updated_box = fcstd_with_plm_revision(
            make_fcstd_bytes("Box geaendert", xlinks=[("Chip.FCStd", "VarSet")]),
            "R0002",
        )
        noisy_deckel = noisy_fcstd_bytes(deckel_revision.file.read(), plm_revision="R0002")
        metadata = [
            {
                "field": "file_0",
                "path": "Box.FCStd",
                "revision_id": box_revision.id,
                "base_sha256": box_revision.sha256,
                "sha256": sha256(updated_box).hexdigest(),
                "is_root": False,
            },
            {
                "field": "file_1",
                "path": "Deckel.FCStd",
                "revision_id": deckel_revision.id,
                "base_sha256": deckel_revision.sha256,
                "sha256": sha256(noisy_deckel).hexdigest(),
                "is_root": False,
            },
        ]

        response = self.client.post(
            reverse("plm:api_checkout_checkin", args=[checkout_id]),
            {
                "files_metadata": json.dumps(metadata),
                "file_0": SimpleUploadedFile("Box.FCStd", updated_box),
                "file_1": SimpleUploadedFile("Deckel.FCStd", noisy_deckel),
                "change_summary": "Box angepasst, Deckel nur gespeichert.",
            },
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual([item["path"] for item in payload["revisions"]], ["Box.FCStd"])
        self.assertEqual(
            payload["ignored_files"],
            [{"path": "Deckel.FCStd", "reason": "no_model_change"}],
        )
        self.assertTrue(
            Revision.objects.filter(part=box_revision.part, revision_code="R0002").exists()
        )
        self.assertFalse(
            Revision.objects.filter(part=deckel_revision.part, revision_code="R0002").exists()
        )
        new_snapshot = ProjectSnapshot.objects.exclude(id=snapshot.id).get()
        self.assertEqual(new_snapshot.entries.get(path="Deckel.FCStd").revision, deckel_revision)

    def test_multi_file_checkin_with_only_technical_changes_keeps_checkout_active(self):
        self.authorize_token([ApiToken.Scope.READ, ApiToken.Scope.CHECKOUT])
        snapshot = import_project_snapshot(
            self.project,
            make_project_zip_upload(),
            self.user,
            name="Arbeitsstand",
        )
        root_revision = Revision.objects.get(part__name="Druck")
        box_revision = Revision.objects.get(part__name="Box")
        checkout_response = self.post_json(
            reverse("plm:api_revision_checkout", args=[root_revision.id]),
            {"snapshot_id": snapshot.id},
        )
        checkout_id = checkout_response.json()["checkout"]["id"]
        noisy_box = noisy_fcstd_bytes(box_revision.file.read(), plm_revision="R0002")
        metadata = [
            {
                "field": "file_0",
                "path": "Box.FCStd",
                "revision_id": box_revision.id,
                "base_sha256": box_revision.sha256,
                "sha256": sha256(noisy_box).hexdigest(),
                "is_root": False,
            }
        ]

        response = self.client.post(
            reverse("plm:api_checkout_checkin", args=[checkout_id]),
            {
                "files_metadata": json.dumps(metadata),
                "file_0": SimpleUploadedFile("Box.FCStd", noisy_box),
            },
        )

        self.assertEqual(response.status_code, 200)
        checkout = Checkout.objects.get(id=checkout_id)
        self.assertEqual(checkout.status, Checkout.Status.ACTIVE)
        payload = response.json()
        self.assertIsNone(payload["revision"])
        self.assertEqual(payload["revisions"], [])
        self.assertEqual(
            payload["ignored_files"],
            [{"path": "Box.FCStd", "reason": "no_model_change"}],
        )
        self.assertEqual(ProjectSnapshot.objects.count(), 1)
        self.assertFalse(
            Revision.objects.filter(part=box_revision.part, revision_code="R0002").exists()
        )

    def test_multi_file_checkin_rejects_unknown_manifest_path_and_keeps_checkout_active(self):
        self.authorize_token([ApiToken.Scope.READ, ApiToken.Scope.CHECKOUT])
        snapshot = import_project_snapshot(
            self.project,
            make_project_zip_upload(),
            self.user,
            name="Arbeitsstand",
        )
        root_revision = Revision.objects.get(part__name="Druck")
        box_revision = Revision.objects.get(part__name="Box")
        checkout_response = self.post_json(
            reverse("plm:api_revision_checkout", args=[root_revision.id]),
            {"snapshot_id": snapshot.id},
        )
        checkout_id = checkout_response.json()["checkout"]["id"]
        updated_box = fcstd_with_plm_revision(
            make_fcstd_bytes("Box geaendert", xlinks=[("Chip.FCStd", "VarSet")]),
            "R0002",
        )
        metadata = [
            {
                "field": "file_0",
                "path": "../Box.FCStd",
                "revision_id": box_revision.id,
                "base_sha256": box_revision.sha256,
                "sha256": sha256(updated_box).hexdigest(),
                "is_root": False,
            }
        ]

        response = self.client.post(
            reverse("plm:api_checkout_checkin", args=[checkout_id]),
            {
                "files_metadata": json.dumps(metadata),
                "file_0": SimpleUploadedFile("Box.FCStd", updated_box),
            },
        )

        self.assertEqual(response.status_code, 409)
        checkout = Checkout.objects.get(id=checkout_id)
        self.assertEqual(checkout.status, Checkout.Status.ACTIVE)
        self.assertFalse(
            Revision.objects.filter(part=box_revision.part, revision_code="R0002").exists()
        )

    def test_annotations_can_target_freecad_objects(self):
        self.authorize_token([ApiToken.Scope.READ, ApiToken.Scope.WRITE])
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)

        response = self.post_json(
            reverse("plm:api_part_annotations", args=[self.part.id]),
            {
                "revision_id": revision.id,
                "object_name": "Body",
                "subelement": "Face12",
                "text": "Kante beim naechsten Check-in abrunden.",
            },
        )

        self.assertEqual(response.status_code, 201)
        annotation = Annotation.objects.get()
        self.assertEqual(annotation.object_name, "Body")
        self.assertEqual(annotation.subelement, "Face12")
        self.assertEqual(annotation.revision, revision)

        response = self.client.get(
            reverse("plm:api_part_annotations", args=[self.part.id])
        )
        self.assertEqual(response.json()["annotations"][0]["object_name"], "Body")

    def test_annotation_create_ignores_non_string_optional_targets(self):
        self.authorize_token([ApiToken.Scope.READ, ApiToken.Scope.WRITE])
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)

        response = self.post_json(
            reverse("plm:api_part_annotations", args=[self.part.id]),
            {
                "revision_id": revision.id,
                "object_name": False,
                "subelement": None,
                "text": "Panel-Button ohne Selektion.",
            },
        )

        self.assertEqual(response.status_code, 201)
        annotation = Annotation.objects.get()
        self.assertEqual(annotation.object_name, "")
        self.assertEqual(annotation.subelement, "")

    def test_api_can_update_revision_notes_without_new_revision(self):
        self.authorize_token([ApiToken.Scope.WRITE])
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)

        response = self.post_json(
            reverse("plm:api_revision_notes", args=[revision.id]),
            {"notes": "  In Baugruppe pruefen.  "},
        )

        self.assertEqual(response.status_code, 200)
        revision.refresh_from_db()
        self.assertEqual(revision.notes, "In Baugruppe pruefen.")
        self.assertEqual(Revision.objects.count(), 1)
        self.assertEqual(response.json()["revision"]["notes"], "In Baugruppe pruefen.")
        self.assertTrue(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.REVISION_NOTES_UPDATED,
                metadata__revision_id=revision.id,
            ).exists()
        )

    def test_api_can_delete_annotation_without_new_revision(self):
        self.authorize_token([ApiToken.Scope.WRITE])
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)
        annotation = Annotation.objects.create(
            project=self.project,
            part=self.part,
            revision=revision,
            created_by=self.user,
            text="Nicht mehr relevant.",
        )

        response = self.client.delete(reverse("plm:api_annotation", args=[annotation.id]))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Annotation.objects.filter(id=annotation.id).exists())
        self.assertEqual(Revision.objects.count(), 1)
        self.assertTrue(
            AuditEvent.objects.filter(
                action=AuditEvent.Action.ANNOTATION_DELETED,
                metadata__annotation_id=annotation.id,
            ).exists()
        )
