from io import BytesIO
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from .fcstd import validate_fcstd_upload
from .models import AuditEvent, Part, Project, Revision
from .services import create_revision_from_upload, next_revision_code


def make_zip_upload(name="part.FCStd", members=None):
    members = members or {"Document.xml": "<Document />"}
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for member_name, content in members.items():
            archive.writestr(member_name, content)
    return SimpleUploadedFile(name, buffer.getvalue())


class FcstdValidationTests(SimpleTestCase):
    def test_accepts_fcstd_zip_and_returns_metadata(self):
        upload = make_zip_upload(
            members={
                "Document.xml": "<Document />",
                "GuiDocument.xml": "<GuiDocument />",
            },
        )

        metadata = validate_fcstd_upload(upload)

        self.assertEqual(metadata["original_filename"], "part.FCStd")
        self.assertEqual(metadata["zip_member_count"], 2)
        self.assertTrue(metadata["has_document_xml"])
        self.assertTrue(metadata["has_gui_document_xml"])
        self.assertEqual(len(metadata["sha256"]), 64)
        self.assertGreater(metadata["size_bytes"], 0)

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

    def test_next_revision_code_starts_at_r0001(self):
        self.assertEqual(next_revision_code(self.part), "R0001")

    def test_create_revision_from_upload_stores_revision_metadata_and_audit(self):
        upload = make_zip_upload(
            members={
                "Document.xml": "<Document />",
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
        self.assertTrue(revision.file.storage.exists(revision.file.name))
        self.assertEqual(AuditEvent.objects.count(), 1)

    def test_create_revision_from_upload_increments_revision_code(self):
        create_revision_from_upload(self.part, make_zip_upload(), self.user)

        revision = create_revision_from_upload(self.part, make_zip_upload(), self.user)

        self.assertEqual(revision.revision_code, "R0002")

    def test_invalid_upload_does_not_create_revision(self):
        upload = SimpleUploadedFile("part.FCStd", b"not a zip")

        with self.assertRaises(ValidationError):
            create_revision_from_upload(self.part, upload, self.user)

        self.assertFalse(Revision.objects.exists())
        self.assertFalse(AuditEvent.objects.exists())
