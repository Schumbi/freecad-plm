import json
from datetime import date
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

from .fcstd import fcstd_with_plm_revision, validate_fcstd_upload
from .models import (
    Annotation,
    AuditEvent,
    Checkout,
    ExportJob,
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


def make_zip_upload(name="part.FCStd", members=None):
    members = members or {
        "Document.xml": FREECAD_DOCUMENT_XML,
    }
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for member_name, content in members.items():
            write_zip_member(archive, member_name, content)
    return SimpleUploadedFile(name, buffer.getvalue())


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
        self.assertGreater(metadata["size_bytes"], 0)

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
        self.assertEqual(AuditEvent.objects.count(), 1)

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
        messages = list(response.wsgi_request._messages)
        self.assertIn("5 neue Revisionen", str(messages[0]))
        self.assertIn("0 unveraenderte Dateien", str(messages[0]))

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

    def test_editor_can_upload_revision(self):
        self.assertTrue(can_upload_revision(self.editor))

        self.client.force_login(self.editor)
        response = self.client.post(
            reverse("plm:upload_revision", args=[self.part.id]),
            {"file": make_zip_upload()},
        )

        self.assertRedirects(response, reverse("plm:part_detail", args=[self.part.id]))
        self.assertEqual(Revision.objects.count(), 1)

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

    def login(self):
        self.client.force_login(self.user)

    def post_json(self, url, payload):
        return self.client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
        )

    def test_api_lists_projects_and_creates_parts(self):
        self.login()

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

    def test_checkout_manifest_contains_snapshot_exact_dependencies(self):
        self.login()
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

    def test_second_active_checkout_for_same_part_is_rejected(self):
        self.login()
        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)
        url = reverse("plm:api_revision_checkout", args=[revision.id])

        first = self.post_json(url, {})
        second = self.post_json(url, {})

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(Checkout.objects.count(), 1)

    def test_checkin_creates_new_revision_and_completes_checkout(self):
        self.login()
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

    def test_annotations_can_target_freecad_objects(self):
        self.login()
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
