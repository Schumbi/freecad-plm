from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .auth import create_api_token
from .models import ApiToken, Part, Project, ProjectDocumentVersion, ProjectSnapshot, ProjectSnapshotEntry, Revision
from .services.documents import upload_document, copy_snapshot_documents
from .services.snapshots import import_project_snapshot


class ProjectDocumentTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media_override = override_settings(MEDIA_ROOT=self.temp.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.admin = get_user_model().objects.create_superuser(username="doc-admin", password="test")
        self.reader = get_user_model().objects.create_user(username="doc-reader", password="test")
        self.project = Project.objects.create(code="DOC", name="Documents")
        _, token = create_api_token(user=self.admin, name="admin", scopes=[ApiToken.Scope.ADMIN])
        self.auth = {"HTTP_AUTHORIZATION": "Bearer " + token}

    def test_upload_reuses_identical_content_and_preserves_snapshot_versions(self):
        first, created = upload_document(self.project, "Specs/brief.pdf", SimpleUploadedFile("brief.pdf", b"%PDF-1.4 old"), self.admin)
        self.assertTrue(created)
        reused, created = upload_document(self.project, "Specs/brief.pdf", SimpleUploadedFile("brief.pdf", b"%PDF-1.4 old"), self.admin)
        self.assertFalse(created)
        self.assertEqual(reused.pk, first.pk)
        archive = BytesIO()
        with ZipFile(archive, "w") as zip_file:
            zip_file.writestr("Specs/brief.pdf", b"%PDF-1.4 new")
        snapshot = import_project_snapshot(self.project, SimpleUploadedFile("docs.zip", archive.getvalue()), self.admin)
        self.assertEqual(snapshot.entries.count(), 0)
        self.assertEqual(snapshot.documents.count(), 1)
        self.assertEqual(snapshot.documents.first().version.number, 2)
        copied = type(snapshot).objects.create(project=self.project, name="Check-in", created_by=self.admin)
        copy_snapshot_documents(snapshot, copied)
        self.assertEqual(copied.documents.first().version_id, snapshot.documents.first().version_id)
        upload_document(self.project, "Specs/brief.pdf", SimpleUploadedFile("brief.pdf", b"%PDF-1.4 newest"), self.admin)
        self.client.force_login(self.reader)
        response = self.client.get(reverse("plm:download_project_snapshot", args=[copied.pk]))
        with ZipFile(BytesIO(b"".join(response.streaming_content))) as result:
            self.assertEqual(result.read("Dokumente/Specs/brief.pdf"), b"%PDF-1.4 new")

    @override_settings(PLM_MAX_PROJECT_DOCUMENT_BYTES=4)
    def test_size_limit_and_unsafe_paths(self):
        response = self.client.post(f"/api/projects/{self.project.pk}/documents/",
            {"path": "safe.txt", "file": SimpleUploadedFile("safe.txt", b"12345")}, **self.auth)
        self.assertEqual(response.status_code, 400)
        response = self.client.post(f"/api/projects/{self.project.pk}/documents/",
            {"path": "../secret.txt", "file": SimpleUploadedFile("secret.txt", b"1234")}, **self.auth)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ProjectDocumentVersion.objects.count(), 0)

    def test_reader_can_download_but_cannot_upload_or_archive(self):
        version, _ = upload_document(self.project, "readme.txt", SimpleUploadedFile("readme.txt", b"hello"), self.admin)
        _, token = create_api_token(user=self.reader, name="read", scopes=[ApiToken.Scope.READ])
        auth = {"HTTP_AUTHORIZATION": "Bearer " + token}
        response = self.client.get(f"/api/document-versions/{version.pk}/file/", **auth)
        self.assertEqual(response.status_code, 200)
        response.close()
        self.assertEqual(self.client.post(f"/api/projects/{self.project.pk}/documents/",
            {"file": SimpleUploadedFile("a", b"a")}, **auth).status_code, 403)
        self.assertEqual(self.client.post(f"/api/documents/{version.document_id}/", {"action": "archive"}, **auth).status_code, 403)

    def test_archive_restore_and_reupload_preserve_history(self):
        first, _ = upload_document(self.project, "notes.txt", SimpleUploadedFile("notes.txt", b"first"), self.admin)
        url = f"/api/documents/{first.document_id}/"
        self.assertTrue(self.client.post(url, {"action": "archive"}, **self.auth).json()["document"]["is_archived"])
        self.assertFalse(self.client.post(url, {"action": "restore"}, **self.auth).json()["document"]["is_archived"])
        second, created = upload_document(self.project, "notes.txt", SimpleUploadedFile("notes.txt", b"second"), self.admin)
        self.assertTrue(created)
        self.assertEqual(second.number, 2)
        third, created = upload_document(self.project, "notes.txt", SimpleUploadedFile("notes.txt", b"first"), self.admin)
        self.assertTrue(created)
        self.assertEqual(third.number, 3)
        self.assertEqual(third.file.name, first.file.name)
        self.assertEqual(list(first.document.versions.values_list("number", flat=True)), [3, 2, 1])

    def test_web_file_overview_and_documents_render(self):
        upload_document(self.project, "manual.pdf", SimpleUploadedFile("manual.pdf", b"%PDF-1.4"), self.admin)
        self.client.force_login(self.reader)
        self.assertContains(self.client.get(reverse("plm:project_detail", args=[self.project.pk])), "Dateien und Abhängigkeiten")
        self.assertContains(self.client.get(reverse("plm:project_files_overview", args=[self.project.pk])), "manual.pdf")
        self.assertContains(self.client.get(reverse("plm:project_documents", args=[self.project.pk])), "PDF ansehen")

    def test_overview_handles_missing_and_cyclic_references_and_compares_snapshots(self):
        part = Part.objects.create(project=self.project, number="P-001", name="Part")
        first = Revision.objects.create(part=part, revision_code="R1", file_format="fcstd",
            original_filename="one.FCStd", sha256="a" * 64, size_bytes=3, created_by=self.admin,
            extracted_metadata={"freecad_document": {"references": [
                {"file": "two.FCStd", "name": "Body"},
                {"file": "two.FCStd", "name": "Sketch"},
                {"file": "two.FCStd", "name": "Parameters"},
                {"file": "missing.FCStd"},
            ]}})
        first.file.save("one.FCStd", SimpleUploadedFile("one.FCStd", b"one"))
        second = Revision.objects.create(part=part, revision_code="R2", file_format="fcstd",
            original_filename="two.FCStd", sha256="b" * 64, size_bytes=3, created_by=self.admin,
            extracted_metadata={"freecad_document": {"references": [{"file": "one.FCStd"}]}})
        second.file.save("two.FCStd", SimpleUploadedFile("two.FCStd", b"two"))
        old = ProjectSnapshot.objects.create(project=self.project, name="Old", created_by=self.admin)
        ProjectSnapshotEntry.objects.create(snapshot=old, path="one.FCStd", revision=first)
        new = ProjectSnapshot.objects.create(project=self.project, name="New", created_by=self.admin)
        ProjectSnapshotEntry.objects.create(snapshot=new, path="one.FCStd", revision=first)
        ProjectSnapshotEntry.objects.create(snapshot=new, path="two.FCStd", revision=second)
        self.client.force_login(self.reader)
        response = self.client.get(reverse("plm:project_files_overview", args=[self.project.pk]),
            {"snapshot": new.pk, "compare": old.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "missing.FCStd")
        self.assertContains(response, "Fehlt")
        self.assertContains(response, "Hinzugefügt")
        self.assertContains(response, "Zyklus")
        self.assertContains(response, "Wird verwendet von")
        self.assertEqual(
            [link for link in response.context["dependencies"] if link["source"] == "one.FCStd" and link["target"] == "two.FCStd"],
            [{"source": "one.FCStd", "target": "two.FCStd", "state": "Eindeutig"}],
        )
