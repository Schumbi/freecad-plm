from io import BytesIO
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
from unittest.mock import patch
from xml.etree import ElementTree

from django.contrib.auth import get_user_model
from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .auth import create_api_token
from .models import ApiToken, Checkout, Part, PartFamily, Project, ProjectVariant, Revision
from .services import create_revision_from_upload, import_project_snapshot, delete_project_tree
from .tests import make_fcstd_bytes, make_project_zip_upload


class RodelnVariantMigrationTests(TestCase):
    def test_existing_chipbox_parts_are_grouped_by_execution_and_role(self):
        project = Project.objects.create(code="RODELN", name="Chipboxen")
        assembly = PartFamily.objects.create(project=project, name="Zusammenbau")
        printing = PartFamily.objects.create(project=project, name="Druck")
        groups = (
            ("A-001", "A-002", "P-001", "P-002", "P-003"),
            ("P-004", "P-005", "P-006", "P-007", "P-008"),
            ("P-009", "P-010", "P-011", "P-012", "P-013"),
        )
        for numbers in groups:
            for number in numbers:
                family = assembly if number in ("A-002", "P-008", "P-013") else printing if number in ("A-001", "P-004", "P-009") else None
                Part.objects.create(project=project, number=number, name=number, family=family)
        extra = Part.objects.create(project=project, number="P-014", name="Maskottchen")

        import_module("plm.migrations.0034_project_variants").configure_rodeln(apps, None)

        project.refresh_from_db()
        self.assertEqual((project.variant_assembly_family_id, project.variant_print_family_id),
                         (assembly.id, printing.id))
        self.assertEqual([variant.name for variant in project.variants.all()], ["Normal", "12 Chips", "20 Chips"])
        for variant, numbers in zip(project.variants.all(), groups):
            self.assertEqual(set(variant.parts.values_list("number", flat=True)), set(numbers))
        extra.refresh_from_db()
        self.assertIsNone(extra.project_variant_id)


class VariantTests(TestCase):
    def setUp(self):
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.settings_context = override_settings(MEDIA_ROOT=self.media.name, ALLOWED_HOSTS=["testserver"])
        self.settings_context.enable()
        self.addCleanup(self.settings_context.disable)
        self.user = get_user_model().objects.create_user(username="variants", is_superuser=True)
        self.project = Project.objects.create(code="BOX", name="Chipbox")
        self.part = Part.objects.create(project=self.project, number="BOX-25", name="Chipbox")
        self.source = create_revision_from_upload(
            self.part, SimpleUploadedFile("Box.FCStd", make_fcstd_bytes("Box")), self.user,
            normalize_plm_revision=True,
        )
        self.authorize()

    def authorize(self, scopes=None, user=None):
        _, token = create_api_token(user=user or self.user, name="variants", scopes=scopes or ["read", "write", "checkout"])
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"

    def create(self, **fields):
        data = {"name": "Chipbox – 20 Chips", "source_revision_id": self.source.id,
                "file": SimpleUploadedFile("Box.FCStd", make_fcstd_bytes("Box20"))}
        data.update(fields)
        return self.client.post(reverse("plm:api_create_fcstd_part", args=[self.project.id]), data)

    def test_independent_variant_family_revision_checkout_and_siblings(self):
        source_hash = self.source.sha256
        response = self.create()
        self.assertEqual(response.status_code, 201, response.content)
        variant = Part.objects.get(pk=response.json()["part"]["id"])
        self.part.refresh_from_db()
        self.assertEqual(variant.family_id, self.part.family_id)
        self.assertEqual(variant.project_variant.name, "Chipbox – 20 Chips")
        self.assertEqual(variant.variant_source_revision_id, self.source.id)
        self.assertEqual(variant.revisions.get().revision_code, "R0001")
        self.assertEqual(variant.checkouts.get().status, Checkout.Status.ACTIVE)
        self.source.refresh_from_db()
        self.assertEqual(self.source.sha256, source_hash)
        self.assertEqual(self.part.revisions.count(), 1)
        another = self.create(name="Chipbox – 10 Chips")
        self.assertEqual(another.status_code, 201, another.content)
        self.assertEqual(PartFamily.objects.count(), 1)
        self.assertEqual(ProjectVariant.objects.filter(project=self.project).count(), 2)
        detail = self.client.get(reverse("plm:api_part", args=[variant.id])).json()
        self.assertEqual(len(detail["variants"]), 3)
        self.assertTrue(detail["can_create_variant"])
        self.assertFalse(variant.revisions.get().primary_print_projects.exists())
        self.client.force_login(self.user)
        page = self.client.get(reverse("plm:part_detail", args=[variant.id]))
        self.assertContains(page, "Teilefamilie: Chipbox")
        self.assertContains(page, "Chipbox – 10 Chips")

    def test_project_parts_exposes_configured_variant_view(self):
        created = self.create()
        self.assertEqual(created.status_code, 201, created.content)
        derived = Part.objects.get(pk=created.json()["part"]["id"])
        self.part.refresh_from_db()
        normal = ProjectVariant.objects.create(project=self.project, name="Normal", position=0)
        self.part.project_variant = normal
        self.part.save(update_fields=["project_variant"])
        print_family = PartFamily.objects.create(project=self.project, name="Druck")
        normal_print = Part.objects.create(project=self.project, number="PRINT-1", name="Druck", family=print_family, project_variant=normal)
        derived_print = Part.objects.create(project=self.project, number="PRINT-2", name="Druck 20", family=print_family, project_variant=derived.project_variant)
        self.project.variant_assembly_family = self.part.family
        self.project.variant_print_family = print_family
        self.project.save(update_fields=["variant_assembly_family", "variant_print_family"])

        response = self.client.get(reverse("plm:api_project_parts", args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        rows = response.json()["variant_view"]["rows"]
        self.assertEqual([row["name"] for row in rows], ["Normal", "Chipbox – 20 Chips"])
        self.assertEqual([(row["assembly_part_id"], row["print_part_id"]) for row in rows],
                         [(self.part.id, normal_print.id), (derived.id, derived_print.id)])

    def test_permissions_and_scopes_enforced_before_mutation(self):
        reader = get_user_model().objects.create_user(username="reader")
        for scopes, user in [(["read", "write", "checkout"], reader), (["read", "write"], self.user), (["read", "checkout"], self.user)]:
            self.authorize(scopes, user)
            self.assertEqual(self.create().status_code, 403)
            detail = self.client.get(reverse("plm:api_part", args=[self.part.id]))
            self.assertFalse(detail.json()["can_create_variant"])
        self.assertEqual(Part.objects.count(), 1)
        self.assertEqual(PartFamily.objects.count(), 0)

    def test_bad_upload_and_duplicate_number_leave_no_family_or_files(self):
        for fields in [{"file": SimpleUploadedFile("Box.FCStd", b"bad")}, {"number": self.part.number}, {"source_revision_id": "bad"}]:
            response = self.create(**fields)
            self.assertIn(response.status_code, (400, 409))
        self.part.refresh_from_db()
        self.assertIsNone(self.part.family_id)
        self.assertEqual(Revision.objects.count(), 1)

    def test_source_must_belong_to_project_and_be_active(self):
        other = Project.objects.create(code="OTHER", name="Other")
        self.assertEqual(self.client.post(reverse("plm:api_create_fcstd_part", args=[other.id]), {
            "source_revision_id": self.source.id, "file": SimpleUploadedFile("Box.FCStd", make_fcstd_bytes("Box")),
        }).status_code, 404)
        self.part.is_archived = True
        self.part.save()
        self.assertEqual(self.create().status_code, 409)

    def linked_source(self, real=False):
        upload = make_project_zip_upload()
        if real:
            upload = SimpleUploadedFile("chipbox.zip", (Path(__file__).resolve().parent / "fixtures/chipbox-variants.zip").read_bytes())
        snapshot = import_project_snapshot(self.project, upload, self.user)
        entry = snapshot.entries.filter(path__endswith="Druck.FCStd").get()
        self.source = entry.revision
        return snapshot

    def bundle(self, snapshot, missing=None, broken=False, chip_count=None):
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            for entry in snapshot.entries.select_related("revision"):
                if entry.path.endswith("Zusammenbau.FCStd") or entry.path == missing:
                    continue
                with entry.revision.file.open("rb") as file:
                    data = file.read()
                if broken and entry.path.endswith("Chip.FCStd"):
                    data = b"invalid"
                if chip_count is not None and entry.path.endswith("Chip.FCStd"):
                    target = BytesIO()
                    with ZipFile(BytesIO(data)) as original, ZipFile(target, "w") as updated:
                        for info in original.infolist():
                            content = original.read(info)
                            if info.filename == "Document.xml":
                                xml = ElementTree.fromstring(content)
                                xml.find(".//Property[@name='Box_anzahlChips']/Integer").set("value", str(chip_count))
                                content = ElementTree.tostring(xml, encoding="utf-8")
                            updated.writestr(info, content)
                    data = target.getvalue()
                archive.writestr(entry.path, data)
        return SimpleUploadedFile("variant.zip", buffer.getvalue())

    def test_linked_chipbox_clones_entire_graph_including_parameters(self):
        snapshot = self.linked_source()
        original_ids = set(snapshot.entries.values_list("revision_id", flat=True))
        response = self.create(file=self.bundle(snapshot), source_snapshot_id=snapshot.id)
        self.assertEqual(response.status_code, 201, response.content)
        manifest = response.json()["manifest"]
        self.assertEqual({item["path"] for item in manifest["files"]}, {"Druck.FCStd", "Box.FCStd", "Deckel.FCStd", "Chip.FCStd"})
        self.assertFalse(original_ids & {item["revision_id"] for item in manifest["files"]})
        for item in manifest["files"]:
            revision = Revision.objects.get(pk=item["revision_id"])
            self.assertEqual(revision.revision_code, "R0001")
            self.assertIsNotNone(revision.part.variant_source_revision_id)

    def test_real_repository_chipbox_can_be_stored_as_independent_variant(self):
        snapshot = self.linked_source(real=True)
        response = self.create(file=self.bundle(snapshot, chip_count=20), source_snapshot_id=snapshot.id)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(len(response.json()["manifest"]["files"]), 4)
        source_chip = snapshot.entries.get(path="Chip.FCStd").revision
        chip_item = next(item for item in response.json()["manifest"]["files"] if item["path"] == "Chip.FCStd")
        variant_chip = Revision.objects.get(pk=chip_item["revision_id"])
        for revision, expected in [(source_chip, "25"), (variant_chip, "20")]:
            with revision.file.open("rb") as file, ZipFile(file) as archive:
                xml = ElementTree.fromstring(archive.read("Document.xml"))
                self.assertEqual(xml.find(".//Property[@name='Box_anzahlChips']/Integer").get("value"), expected)

    def test_incomplete_or_invalid_dependency_bundle_is_atomic(self):
        snapshot = self.linked_source()
        count = Part.objects.count()
        for kwargs in [{"missing": "Chip.FCStd"}, {"broken": True}]:
            response = self.create(file=self.bundle(snapshot, **kwargs), source_snapshot_id=snapshot.id)
            self.assertEqual(response.status_code, 409, response.content)
            self.assertEqual(Part.objects.count(), count)
            self.assertEqual(PartFamily.objects.count(), 0)

    def test_project_deletion_handles_variant_provenance_and_families(self):
        self.assertEqual(self.create().status_code, 201)
        delete_project_tree(self.project, self.user)
        self.assertEqual(PartFamily.objects.count(), 0)
        self.assertEqual(Part.objects.count(), 0)

    def test_failure_after_file_storage_rolls_back_and_cleans_variant_files(self):
        files_before = {path for path in Path(self.media.name).rglob("*") if path.is_file()}
        with patch("plm.services.variants.create_checkout", side_effect=ValidationError("Checkout fehlgeschlagen")):
            self.assertEqual(self.create().status_code, 409)
        self.assertEqual(PartFamily.objects.count(), 0)
        self.assertEqual(Part.objects.count(), 1)
        self.assertEqual(files_before, {path for path in Path(self.media.name).rglob("*") if path.is_file()})
