from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from tempfile import TemporaryDirectory
from django.contrib.auth import get_user_model
from .models import Project
from .services import import_project_snapshot, create_checkout
from .services.manifests import revision_manifest
from .services.snapshots import create_snapshot_from_checkout_revisions
from .services.variants import create_variant_checkout
from .tests import make_project_zip_upload, make_zip_upload, STEP_DATA, ASCII_STL_DATA


class DependencyImportTests(TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        settings = override_settings(MEDIA_ROOT=tmp.name, PROCESS_EXPORT_JOBS_INLINE=False)
        settings.enable()
        self.addCleanup(settings.disable)
        self.user = get_user_model().objects.create_superuser(username="importer", password="x")
        self.project = Project.objects.create(code="IMP", name="Import")

    def upload(self, members):
        return make_project_zip_upload("project.zip", members=members)

    def test_single_root_and_checkout_snapshot_preserves_dependencies(self):
        snapshot = import_project_snapshot(self.project, self.upload({"cad/root.FCStd": make_zip_upload().read(), "mesh/a.stl": ASCII_STL_DATA, "vendor/a.step": STEP_DATA}), self.user)
        root = snapshot.entries.get(path="cad/root.FCStd").revision
        self.assertEqual({item["path"] for item in revision_manifest(root, snapshot)["files"]}, {"cad/root.FCStd", "mesh/a.stl", "vendor/a.step"})
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("plm:part_detail", args=[root.part_id])), "vendor/a.step")
        checkout = create_checkout(root, self.user, snapshot=snapshot)
        checkout.removed_paths = ["mesh/a.stl"]
        checkout.save(update_fields=["removed_paths"])
        next_snapshot = create_snapshot_from_checkout_revisions(checkout, self.user, [])
        self.assertEqual({item["path"] for item in revision_manifest(root, next_snapshot)["files"]}, {"cad/root.FCStd", "vendor/a.step"})

    def test_multiple_roots_require_and_honor_selection(self):
        members = {"one.FCStd": make_zip_upload().read(), "two.FCStd": make_zip_upload().read(), "a.stl": ASCII_STL_DATA}
        with self.assertRaises(ValidationError):
            import_project_snapshot(self.project, self.upload(members), self.user)
        snapshot = import_project_snapshot(self.project, self.upload(members), self.user, dependency_root_path="two.FCStd")
        self.assertEqual(snapshot.entries.get(path="a.stl").dependency_root_path, "two.FCStd")

    def test_external_only_requires_existing_project_revision(self):
        members = {"vendor/a.step": STEP_DATA}
        with self.assertRaises(ValidationError):
            import_project_snapshot(self.project, self.upload(members), self.user)
        first = import_project_snapshot(self.project, self.upload({"root.FCStd": make_zip_upload().read()}), self.user)
        root = first.entries.get().revision
        second = import_project_snapshot(self.project, self.upload(members), self.user, dependency_revision_id=root.id)
        self.assertEqual({item["path"] for item in revision_manifest(root, second)["files"]}, {"root.FCStd", "vendor/a.step"})

    def test_web_multiple_roots_selection(self):
        self.client.force_login(self.user)
        url = reverse("plm:upload_project_snapshot", args=[self.project.id])
        members = {"one.FCStd": make_zip_upload().read(), "two.FCStd": make_zip_upload().read(), "a.stl": ASCII_STL_DATA}
        response = self.client.post(url, {"name": "Test", "file": self.upload(members)})
        self.assertContains(response, "two.FCStd")
        response = self.client.post(url, {"stage": "import", "dependency_root_path": "two.FCStd"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.project.snapshots.get().entries.get(path="a.stl").dependency_root_path, "two.FCStd")

    def test_web_external_only_selects_project_and_root(self):
        first = import_project_snapshot(self.project, self.upload({"root.FCStd": make_zip_upload().read()}), self.user)
        root = first.entries.get().revision
        other = Project.objects.create(code="OTHER", name="Other")
        self.client.force_login(self.user)
        url = reverse("plm:upload_project_snapshot", args=[other.id])
        self.assertContains(self.client.post(url, {"file": self.upload({"a.stl": ASCII_STL_DATA})}), "IMP")
        response = self.client.post(url, {"stage": "project", "target_project": self.project.id})
        self.assertContains(response, root.part.number)
        response = self.client.post(url, {"stage": "import", "target_project": self.project.id, "dependency_revision_id": root.id})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.project.snapshots.count(), 2)

    def test_variant_keeps_imported_dependency(self):
        snapshot = import_project_snapshot(self.project, self.upload({"root.FCStd": make_zip_upload().read(), "a.stl": ASCII_STL_DATA}), self.user)
        root = snapshot.entries.get(path="root.FCStd").revision
        members = {}
        for entry in snapshot.entries.select_related("revision"):
            with entry.revision.file.open("rb") as stream:
                members[entry.path] = stream.read()
        variant, revision, checkout = create_variant_checkout(source_revision=root, uploaded_file=self.upload(members), name="Variante", number="", actor=self.user, snapshot=snapshot)
        self.assertEqual({item["path"] for item in revision_manifest(revision, checkout.snapshot)["files"]}, {"root.FCStd", "a.stl"})
