from io import BytesIO, StringIO
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.urls import reverse
from django.test import SimpleTestCase, TestCase, override_settings

from .fcstd import fcstd_with_plm_revision, validate_fcstd_upload
from .models import AuditEvent, Part, Project, ProjectSnapshot, ProjectSnapshotEntry, Revision
from .permissions import (
    can_edit_revision_notes,
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


def make_zip_upload(name="part.FCStd", members=None):
    members = members or {
        "Document.xml": FREECAD_DOCUMENT_XML,
    }
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for member_name, content in members.items():
            archive.writestr(member_name, content)
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
        archive.writestr(
            "Document.xml",
            freecad_document_xml(label, freecad_id, object_type, xlinks),
        )
    return buffer.getvalue()


def make_project_zip_upload(name="project.zip"):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("Chip.FCStd", make_fcstd_bytes("Chip", object_type="App::VarSet"))
        archive.writestr(
            "Box.FCStd",
            make_fcstd_bytes("Box", xlinks=[("Chip.FCStd", "VarSet")]),
        )
        archive.writestr(
            "Deckel.FCStd",
            make_fcstd_bytes("Deckel", xlinks=[("Chip.FCStd", "VarSet")]),
        )
        archive.writestr(
            "Druck.FCStd",
            make_fcstd_bytes(
                "Druck",
                object_type="Assembly::AssemblyObject",
                xlinks=[("Box.FCStd", "Body"), ("Deckel.FCStd", "Body")],
            ),
        )
        archive.writestr(
            "Zusammenbau.FCStd",
            make_fcstd_bytes(
                "Zusammenbau",
                object_type="Assembly::AssemblyObject",
                xlinks=[("Box.FCStd", "Body"), ("Deckel.FCStd", "Body")],
            ),
        )
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
        self.assertTrue(Part.objects.filter(number="Box").exists())
        self.assertTrue(Part.objects.filter(number="Deckel").exists())
        self.assertEqual(Part.objects.get(number="Chip").category, Part.Category.PART)
        druck = Part.objects.get(number="Druck")
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

    def test_snapshot_entry_download_includes_references_recursively(self):
        self.client.force_login(self.user)
        snapshot = import_project_snapshot(
            self.project,
            make_project_zip_upload(),
            self.user,
            name="Druckstand",
        )
        druck_entry = ProjectSnapshotEntry.objects.get(
            snapshot=snapshot,
            path="Druck.FCStd",
        )

        response = self.client.get(
            reverse(
                "plm:download_snapshot_entry_with_references",
                args=[druck_entry.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        content = b"".join(response.streaming_content)
        with ZipFile(BytesIO(content)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"Box.FCStd", "Chip.FCStd", "Deckel.FCStd", "Druck.FCStd"},
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

    def test_editor_can_upload_revision(self):
        self.assertTrue(can_upload_revision(self.editor))

        self.client.force_login(self.editor)
        response = self.client.post(
            reverse("plm:upload_revision", args=[self.part.id]),
            {"file": make_zip_upload()},
        )

        self.assertRedirects(response, reverse("plm:part_detail", args=[self.part.id]))
        self.assertEqual(Revision.objects.count(), 1)

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
