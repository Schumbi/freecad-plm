from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import AuditEvent, Part, Project, ProjectSnapshot, ProjectSnapshotEntry, Revision


class RemovePartTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.override = override_settings(MEDIA_ROOT=self.tmp.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.admin = get_user_model().objects.create_superuser(username="admin", password="x")
        self.reader = get_user_model().objects.create_user(username="reader", password="x")
        self.project = Project.objects.create(code="HAUS", name="Haus")
        self.part = Part.objects.create(project=self.project, number="P-002", name="Teil")
        self.url = reverse("plm:remove_part", args=[self.part.pk])
        self.client.force_login(self.admin)

    def revision(self, fmt, code="R0001"):
        return Revision.objects.create(part=self.part, revision_code=code, file_format=fmt, file=ContentFile(b"data", name=code + "." + fmt), original_filename="file." + fmt, sha256="a" * 64, size_bytes=4, created_by=self.admin)

    def post(self):
        self.part.refresh_from_db()
        action = "restore" if self.part.is_archived else "archive" if self.part.revisions.filter(file_format="fcstd").exists() else "delete"
        page = self.client.get(self.url)
        return self.client.post(self.url, {"confirmation": "P-002", "action": action, "delete_plan": page.context["delete_plan"] if page.status_code == 200 else ""})

    def test_fcstd_archives_and_restores(self):
        revision = self.revision("fcstd")
        path = revision.file.path
        self.assertEqual(self.post().status_code, 302)
        self.part.refresh_from_db()
        self.assertTrue(self.part.is_archived)
        self.assertTrue(Revision.objects.filter(pk=revision.pk).exists())
        self.assertTrue(__import__("os").path.exists(path))
        self.assertContains(self.client.get(reverse("plm:project_detail", args=[self.project.pk])), "Wiederherstellen")
        self.assertEqual(self.post().status_code, 302)
        self.part.refresh_from_db()
        self.assertFalse(self.part.is_archived)
        self.assertTrue(AuditEvent.objects.filter(action=AuditEvent.Action.PART_RESTORED).exists())

    def test_mixed_revisions_archive(self):
        self.revision("step")
        self.revision("fcstd", "R0002")
        self.post()
        self.part.refresh_from_db()
        self.assertTrue(self.part.is_archived)

    def test_step_and_stl_delete_files_after_commit(self):
        for fmt in ("step", "stl"):
            with self.subTest(fmt=fmt):
                if fmt == "stl":
                    self.part = Part.objects.create(project=self.project, number="P-002", name="Teil")
                    self.url = reverse("plm:remove_part", args=[self.part.pk])
                revision = self.revision(fmt)
                path = revision.file.path
                with self.captureOnCommitCallbacks(execute=True):
                    self.assertEqual(self.post().status_code, 302)
                self.assertFalse(Part.objects.filter(pk=self.part.pk).exists())
                self.assertFalse(__import__("os").path.exists(path))

    def test_snapshot_entry_is_shown_and_removed(self):
        revision = self.revision("stl")
        snapshot = ProjectSnapshot.objects.create(project=self.project, name="Stand", created_by=self.admin)
        ProjectSnapshotEntry.objects.create(snapshot=snapshot, path="file.stl", revision=revision)
        response = self.client.get(self.url)
        self.assertContains(response, "Stand")
        self.assertContains(response, "file.stl")
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.post().status_code, 302)
        self.assertFalse(Revision.objects.filter(pk=revision.pk).exists())
        self.assertTrue(ProjectSnapshot.objects.filter(pk=snapshot.pk).exists())
        self.assertFalse(snapshot.entries.exists())
        event = AuditEvent.objects.get(action=AuditEvent.Action.PART_DELETED)
        self.assertEqual(event.metadata["snapshot_entries"][0]["path"], "file.stl")

    def test_active_checkout_using_snapshot_blocks_deletion(self):
        from .models import Checkout
        revision = self.revision("stl")
        snapshot = ProjectSnapshot.objects.create(project=self.project, name="Stand", created_by=self.admin)
        ProjectSnapshotEntry.objects.create(snapshot=snapshot, path="file.stl", revision=revision)
        root = Part.objects.create(project=self.project, number="P-001", name="Root")
        base = Revision.objects.create(part=root, revision_code="R0001", file_format="fcstd", file=ContentFile(b"root", name="root.FCStd"), original_filename="root.FCStd", sha256="b" * 64, size_bytes=4, created_by=self.admin)
        Checkout.objects.create(part=root, base_revision=base, snapshot=snapshot, checked_out_by=self.admin)
        self.assertEqual(self.post().status_code, 400)
        self.assertTrue(Revision.objects.filter(pk=revision.pk).exists())
        self.assertTrue(snapshot.entries.exists())

    def test_permissions_and_confirmation(self):
        self.revision("step")
        self.assertEqual(self.client.post(self.url, {"confirmation": "wrong"}).status_code, 400)
        self.client.force_login(self.reader)
        self.assertEqual(self.post().status_code, 403)
        self.assertTrue(Part.objects.filter(pk=self.part.pk).exists())

    def test_changed_snapshot_requires_new_confirmation(self):
        revision = self.revision("stl")
        page = self.client.get(self.url)
        snapshot = ProjectSnapshot.objects.create(project=self.project, name="Neu", created_by=self.admin)
        ProjectSnapshotEntry.objects.create(snapshot=snapshot, path="new.stl", revision=revision)
        response = self.client.post(self.url, {"confirmation": "P-002", "action": "delete", "delete_plan": page.context["delete_plan"]})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Revision.objects.filter(pk=revision.pk).exists())
        self.assertTrue(snapshot.entries.exists())
