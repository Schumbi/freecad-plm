"""Regression targets for CODE_REVIEW_2026-09-16 (numbered comments).

expectedFailure means an unfixed defect, not a waived requirement. Remove the
decorator with its fix; unexpected successes deliberately fail the test run.
"""
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Barrier
from unittest import expectedFailure, skipUnless
from unittest.mock import patch
from zipfile import ZipFile
import json

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, connections, transaction
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .models import ApiToken, AuditEvent, ManufacturingFile, PrintProject, PrintProjectPlate, PrintProjectSnapshot, PrintProjectSource
from .review_test_support import PrintProjectFixture, mesh_upload
from .services.common import safe_snapshot_path
from .services.snapshots import delete_project_tree, iter_project_zip_members
from .services.manufacturing import delete_manufacturing_file


class TokenBoundaryTests(PrintProjectFixture, TestCase):
    def test_active_editor_can_read_and_create(self):
        self.assertEqual(self.client.get("/api/print-projects/").status_code, 200)
        self.assertEqual(self.create().status_code, 201)

    def create(self):
        return self.client.post("/api/print-projects/", json.dumps({
            "revision_id": self.revision.pk, "code": "NEW", "name": "New"
        }), content_type="application/json")

    def assert_denied_without_mutation(self, status):
        before = PrintProject.objects.count()
        self.assertEqual(self.create().status_code, status)
        self.assertEqual(PrintProject.objects.count(), before)

    @expectedFailure  # Review 1
    def test_inactive_user_cannot_read(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertEqual(self.client.get("/api/print-projects/").status_code, 401)

    @expectedFailure  # Review 1
    def test_inactive_user_cannot_create(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assert_denied_without_mutation(401)

    def test_revoked_token_cannot_read_or_write(self):
        self.token.revoked_at = timezone.now()
        self.token.save()
        self.assertEqual(self.client.get("/api/print-projects/").status_code, 401)
        self.assert_denied_without_mutation(401)

    def test_expired_token_cannot_read_or_write(self):
        self.token.expires_at = timezone.now() - timedelta(seconds=1)
        self.token.save()
        self.assertEqual(self.client.get("/api/print-projects/").status_code, 401)
        self.assert_denied_without_mutation(401)

    def test_read_scope_cannot_write(self):
        self.token.scopes = [ApiToken.Scope.READ]
        self.token.save()
        self.assertEqual(self.client.get("/api/print-projects/").status_code, 200)
        self.assert_denied_without_mutation(403)

    def test_write_scope_does_not_replace_editor_role(self):
        self.user.groups.clear()
        self.assert_denied_without_mutation(403)

    def assert_uploads_denied(self):
        self.assertEqual(self.upload().status_code, 403)
        response = self.client.post(f"/api/print-projects/{self.item.pk}/sources/", {
            "file": SimpleUploadedFile("source.stl", b"solid x\nendsolid\n")
        })
        self.assertEqual(response.status_code, 403)
        self.item.refresh_from_db()
        self.assertFalse(self.item.slicer_file)
        self.assertFalse(self.item.sources.exists())

    def test_read_scope_cannot_upload_3mf_or_source(self):
        self.token.scopes = [ApiToken.Scope.READ]
        self.token.save()
        self.assert_uploads_denied()

    def test_non_editor_cannot_upload_3mf_or_source(self):
        self.user.groups.clear()
        self.assert_uploads_denied()

    def test_all_four_routes_require_token(self):
        self.client.defaults.clear()
        for method, path in [("get", "/api/print-projects/"), ("get", self.url),
                             ("get", self.url + "file/"),
                             ("post", f"/api/print-projects/{self.item.pk}/sources/")]:
            with self.subTest(method=method, path=path):
                self.assertEqual(getattr(self.client, method)(path).status_code, 401)


class PrintProjectWriteTests(PrintProjectFixture, TestCase):
    def test_matching_base_updates_file_and_hash(self):
        base = self.initial_upload()
        response = self.upload(marker="second", base_sha256=base)
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertNotEqual(self.item.slicer_sha256, base)
        self.assertEqual(response.json()["print_project"]["slicer_project"]["sha256"],
                         self.item.slicer_sha256)

    @expectedFailure  # Review 4: two clients read A, first writes B, second must not overwrite B.
    def test_stale_writer_receives_conflict_and_preserves_current_file(self):
        base = self.initial_upload()
        self.assertEqual(self.upload(marker="second", base_sha256=base).status_code, 200)
        self.item.refresh_from_db()
        current_hash = self.item.slicer_sha256
        current_path = Path(self.item.slicer_file.path)
        current = current_path.read_bytes()
        response = self.upload(marker="stale-writer", base_sha256=base)
        self.assertEqual(response.status_code, 409)
        self.item.refresh_from_db()
        self.assertEqual(self.item.slicer_sha256, current_hash)
        self.assertEqual(Path(self.item.slicer_file.path), current_path)
        self.assertEqual(current_path.read_bytes(), current)
        self.assertEqual(self.item.plates.get().name, "second")

    @expectedFailure  # Review 4: omitted base must not silently overwrite an existing file.
    def test_missing_base_cannot_overwrite_existing_project(self):
        base = self.initial_upload()
        response = self.upload(marker="no-base")
        self.assertIn(response.status_code, (400, 409, 428))
        self.item.refresh_from_db()
        self.assertEqual(self.item.slicer_sha256, base)

    def test_missing_file_leaves_project_unchanged(self):
        base = self.initial_upload()
        response = self.client.post(self.url, {"base_sha256": base})
        self.assertEqual(response.status_code, 400)
        self.item.refresh_from_db()
        self.assertEqual(self.item.slicer_sha256, base)

    def test_non_zip_upload_leaves_project_unchanged(self):
        base = self.initial_upload()
        response = self.client.post(self.url, {
            "base_sha256": base, "file": SimpleUploadedFile("broken.3mf", b"broken")
        })
        self.assertEqual(response.status_code, 400)
        self.item.refresh_from_db()
        self.assertEqual(self.item.slicer_sha256, base)

    @expectedFailure  # Review 8
    def test_empty_geometry_cannot_replace_valid_file(self):
        base = self.initial_upload()
        previous = Path(self.item.slicer_file.path).read_bytes()
        response = self.client.post(self.url, {"file": mesh_upload(geometry=False), "base_sha256": base})
        self.assertEqual(response.status_code, 400)
        self.item.refresh_from_db()
        self.assertEqual(self.item.slicer_sha256, base)
        self.assertEqual(Path(self.item.slicer_file.path).read_bytes(), previous)

    def test_same_revision_allows_distinct_codes(self):
        data = {"revision_id": self.revision.pk, "code": "DP-2", "name": "Second"}
        response = self.client.post("/api/print-projects/", json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertNotEqual(response.json()["print_project"]["id"], self.item.pk)
        response = self.client.post("/api/print-projects/", json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PrintProject.objects.filter(primary_revision=self.revision).count(), 2)

    def test_code_cannot_be_reassigned_to_another_revision(self):
        other = self.make_revision(self.project, "A-002")
        response = self.client.post("/api/print-projects/", json.dumps({
            "revision_id": other.pk, "code": self.item.code, "name": "Reassign"
        }), content_type="application/json")
        self.assertEqual(response.status_code, 409)
        self.item.refresh_from_db()
        self.assertEqual(self.item.primary_revision_id, self.revision.pk)


class PrintProjectStorageTests(PrintProjectFixture, TestCase):
    @expectedFailure  # Review 6
    def test_replacement_removes_old_3mf_only_after_commit(self):
        base = self.initial_upload()
        old_path = Path(self.item.slicer_file.path)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.upload(marker="second", base_sha256=base)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(old_path.exists())
        self.item.refresh_from_db()
        self.assertTrue(Path(self.item.slicer_file.path).is_file())
        self.assertFalse(old_path.exists())

    @expectedFailure  # Review 6: a DB rollback must not destroy the old preview.
    def test_failed_replacement_preserves_previous_preview_and_file(self):
        base = self.initial_upload()
        preview = Path(self.item.plates.get().preview.path)
        file_path = Path(self.item.slicer_file.path)
        previous_files = {path for path in Path(self.media_root).rglob("*") if path.is_file()}
        with patch.object(PrintProjectPlate, "save", side_effect=RuntimeError("injected DB failure")):
            with self.assertRaisesRegex(RuntimeError, "injected DB failure"):
                self.upload(marker="failed", base_sha256=base)
        self.item.refresh_from_db()
        self.assertEqual(self.item.slicer_sha256, base)
        self.assertTrue(file_path.is_file())
        self.assertTrue(preview.is_file())
        self.assertEqual({path for path in Path(self.media_root).rglob("*") if path.is_file()}, previous_files)

    @expectedFailure  # Review 6: include sources, plate previews and archived snapshots.
    def test_delete_project_cleans_print_project_records_and_files(self):
        self.initial_upload()
        PrintProjectSource.objects.create(
            print_project=self.item, source_type=PrintProjectSource.SourceType.EXTERNAL_STL,
            file=SimpleUploadedFile("source.stl", b"solid x\nendsolid\n"),
            original_filename="source.stl", uploaded_by=self.user,
        )
        PrintProjectSnapshot.objects.create(
            print_project=self.item, file=mesh_upload(), original_filename="archive.3mf",
            sha256="b" * 64, size_bytes=1, created_by=self.user,
        )
        project_id, item_id = self.project.pk, self.item.pk
        with self.captureOnCommitCallbacks(execute=True):
            delete_project_tree(self.project, self.user)
        self.assertFalse(type(self.project).objects.filter(pk=project_id).exists())
        self.assertFalse(PrintProject.objects.filter(pk=item_id).exists())
        self.assertFalse(PrintProjectSource.objects.exists())
        self.assertFalse(PrintProjectSnapshot.objects.exists())
        self.assertFalse(PrintProjectPlate.objects.exists())
        self.assertEqual([p for p in Path(self.media_root).rglob("*") if p.is_file()], [])


@skipUnless(connection.vendor == "postgresql", "Concurrent writes require the production PostgreSQL backend")
class PrintProjectConcurrencyTests(PrintProjectFixture, TransactionTestCase):
    @expectedFailure  # Review 4: run again on PostgreSQL when optimistic locking lands.
    def test_only_one_of_two_simultaneous_writers_can_update_the_same_base(self):
        base = self.initial_upload()
        start = Barrier(2, timeout=10)

        def writer(marker):
            client = Client(HTTP_AUTHORIZATION=f"Bearer {self.raw_token}")
            try:
                start.wait()
                response = client.post(self.url, {"file": mesh_upload(marker=marker), "base_sha256": base})
                return marker, response.status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(writer, ["client-a", "client-b"]))
        self.assertEqual(sorted(status for _, status in results), [200, 409])
        winner = next(marker for marker, status in results if status == 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.plates.get().name, winner)


class SnapshotPathTests(SimpleTestCase):
    def test_normal_nested_unicode_path(self):
        self.assertEqual(safe_snapshot_path("Baugruppe/Deckel ä.FCStd"), "Baugruppe/Deckel ä.FCStd")

    def test_posix_escape_rejected(self):
        for name in ("../outside.FCStd", "/outside.FCStd", "parts/../../outside.FCStd"):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                safe_snapshot_path(name)

    @expectedFailure  # Review 3, explicitly simulate a Linux ZIP reader on Windows.
    def test_linux_zip_cannot_supply_windows_traversal(self):
        buffer = BytesIO()
        with patch("zipfile.os.sep", "/"):
            with ZipFile(buffer, "w") as archive:
                archive.writestr(r"..\escape/model.stl", b"solid x\nendsolid\n")
            with self.assertRaises(ValidationError):
                list(iter_project_zip_members(SimpleUploadedFile("unsafe.zip", buffer.getvalue())))


class ManufacturingDeleteTransactionTests(PrintProjectFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.manufacturing = ManufacturingFile.objects.create(
            revision=self.revision, file=mesh_upload(), original_filename="temporary.3mf",
            thumbnail=SimpleUploadedFile("preview.png", b"preview"),
            sha256="c" * 64, size_bytes=1, uploaded_by=self.user,
        )
        self.manufacturing_id = self.manufacturing.pk
        self.files = [Path(self.manufacturing.file.path), Path(self.manufacturing.thumbnail.path)]

    def test_storage_is_deleted_only_after_commit(self):
        with self.captureOnCommitCallbacks(execute=True):
            delete_manufacturing_file(self.manufacturing, self.user)
            self.assertFalse(ManufacturingFile.objects.filter(pk=self.manufacturing_id).exists())
            self.assertTrue(all(p.is_file() for p in self.files))
        self.assertFalse(any(p.exists() for p in self.files))

    def test_rollback_restores_record_files_and_audit(self):
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaisesRegex(RuntimeError, "rollback"):
                with transaction.atomic():
                    delete_manufacturing_file(self.manufacturing, self.user)
                    raise RuntimeError("rollback")
        self.assertTrue(ManufacturingFile.objects.filter(pk=self.manufacturing_id).exists())
        self.assertTrue(all(p.is_file() for p in self.files))
        self.assertFalse(AuditEvent.objects.filter(action=AuditEvent.Action.MANUFACTURING_FILE_DELETED).exists())

    def admin_client(self, **kwargs):
        self.user.is_superuser = True
        self.user.save()
        client = Client(**kwargs)
        client.force_login(self.user)
        return client

    def test_delete_requires_csrf_even_for_admin(self):
        client = self.admin_client(enforce_csrf_checks=True)
        response = client.post(reverse("plm:delete_manufacturing_file", args=[self.manufacturing_id]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(ManufacturingFile.objects.filter(pk=self.manufacturing_id).exists())
        self.assertTrue(all(p.is_file() for p in self.files))

    def test_confirmation_get_does_not_delete(self):
        response = self.admin_client().get(reverse("plm:delete_manufacturing_file", args=[self.manufacturing_id]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ManufacturingFile.objects.filter(pk=self.manufacturing_id).exists())
        self.assertTrue(all(p.is_file() for p in self.files))


def _unsafe_path_case(name):
    def test(self):
        with self.assertRaises(ValidationError):
            safe_snapshot_path(name)
    return expectedFailure(test)


# Separate cases: fixing one representation must not hide the others.
for _label, _path in {
    "windows_parent": r"..\escape/model.FCStd",
    "drive_absolute": r"C:\outside.FCStd",
    "drive_relative": "C:outside.FCStd",
    "unc": r"\\server\share\outside.FCStd",
}.items():
    setattr(SnapshotPathTests, f"test_rejects_{_label}", _unsafe_path_case(_path))
