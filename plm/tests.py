from io import BytesIO
from zipfile import ZipFile

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from .fcstd import validate_fcstd_upload


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
