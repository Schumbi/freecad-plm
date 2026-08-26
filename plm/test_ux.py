import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import (
    Annotation,
    ManufacturingFile,
    ManufacturingRun,
    Part,
    Project,
    ProjectSnapshot,
    ProjectSnapshotEntry,
    Revision,
)
from .permissions import ROLE_EDITOR, ROLE_READER
from .services import (
    assembly_bom_tree,
    part_lifecycle_events,
    search_plm,
    snapshot_entries_with_references,
)


class UxFeatureTests(TestCase):
    def setUp(self):
        editor_group, _created = Group.objects.get_or_create(name=ROLE_EDITOR)
        reader_group, _created = Group.objects.get_or_create(name=ROLE_READER)
        self.editor = get_user_model().objects.create_user("ux-editor", password="pw")
        self.editor.groups.add(editor_group)
        self.reader = get_user_model().objects.create_user("ux-reader", password="pw")
        self.reader.groups.add(reader_group)
        self.project = Project.objects.create(code="UX", name="UX-Projekt")
        self.other_project = Project.objects.create(code="OTHER", name="Anderes Projekt")
        self.assembly = Part.objects.create(
            project=self.project,
            number="A-001",
            name="Baugruppe",
            category=Part.Category.ASSEMBLY,
        )
        self.child = Part.objects.create(
            project=self.project,
            number="P-001",
            name="Kindteil",
            category=Part.Category.PART,
        )
        self.other_part = Part.objects.create(
            project=self.other_project,
            number="P-999",
            name="Fremdteil",
        )
        self.assembly_revision = self.create_revision(
            self.assembly,
            "R0001",
            "Assembly.FCStd",
            Revision.FileFormat.FCSTD,
            Revision.Status.DRAFT,
            references=[{"file": "parts/Child.FCStd", "name": "Body", "sub": ""}],
        )
        self.child_revision = self.create_revision(
            self.child,
            "R0001",
            "Child.step",
            Revision.FileFormat.STEP,
            Revision.Status.RELEASED,
        )
        self.other_revision = self.create_revision(
            self.other_part,
            "R0001",
            "Other.FCStd",
            Revision.FileFormat.FCSTD,
            Revision.Status.DRAFT,
        )

    def create_revision(
        self,
        part,
        code,
        filename,
        file_format,
        status,
        references=None,
    ):
        return Revision.objects.create(
            part=part,
            revision_code=code,
            status=status,
            file=SimpleUploadedFile(filename, b"cad"),
            file_format=file_format,
            original_filename=filename,
            sha256=(str(part.id or 1) * 64)[:64],
            size_bytes=3,
            extracted_metadata={
                "freecad_document": {"references": references or []}
            },
            created_by=self.editor,
        )

    def test_search_facets_filter_project_status_format_and_category(self):
        results = search_plm(
            "",
            project_id=self.project.id,
            revision_status=Revision.Status.RELEASED,
            file_format=Revision.FileFormat.STEP,
            category=Part.Category.PART,
        )

        self.assertEqual(results.projects, [self.project])
        self.assertEqual(results.parts, [self.child])
        self.assertEqual(results.revisions, [self.child_revision])

    def test_search_page_supports_filters_without_query(self):
        self.client.force_login(self.reader)
        response = self.client.get(
            reverse("plm:global_search"),
            {"project": self.project.id, "format": Revision.FileFormat.STEP},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kindteil")
        self.assertNotContains(response, "Fremdteil")

    def test_lifecycle_combines_revision_slicer_file_and_run(self):
        slicer_file = ManufacturingFile.objects.create(
            revision=self.assembly_revision,
            file_type=ManufacturingFile.FileType.SLICER_PROJECT_3MF,
            file=SimpleUploadedFile("Assembly.3mf", b"3mf"),
            original_filename="Assembly.3mf",
            sha256="a" * 64,
            size_bytes=3,
            uploaded_by=self.editor,
        )
        ManufacturingRun.objects.create(
            manufacturing_file=slicer_file,
            status=ManufacturingRun.Status.SUCCEEDED,
            operator=self.editor,
        )

        events = part_lifecycle_events(self.assembly)

        self.assertIn("revision", {event["kind"] for event in events})
        self.assertIn("slicer", {event["kind"] for event in events})
        self.assertIn("run", {event["kind"] for event in events})

    def test_bom_resolves_snapshot_reference_to_child_part(self):
        snapshot = ProjectSnapshot.objects.create(
            project=self.project,
            name="Montage",
            created_by=self.editor,
        )
        root_entry = ProjectSnapshotEntry.objects.create(
            snapshot=snapshot,
            path="Assembly.FCStd",
            revision=self.assembly_revision,
        )
        ProjectSnapshotEntry.objects.create(
            snapshot=snapshot,
            path="parts/Child.FCStd",
            revision=self.child_revision,
        )

        tree = assembly_bom_tree(self.assembly_revision)

        self.assertEqual(tree["snapshot"], snapshot)
        self.assertEqual(tree["children"][0]["revision"], self.child_revision)
        self.assertFalse(tree["children"][0]["missing"])

    def test_bom_does_not_guess_between_duplicate_filenames(self):
        duplicate_part = Part.objects.create(
            project=self.project,
            number="P-003",
            name="Duplicate child",
            category=Part.Category.PART,
        )
        duplicate_revision = self.create_revision(
            duplicate_part,
            "R0001",
            "Child.FCStd",
            Revision.FileFormat.FCSTD,
            Revision.Status.DRAFT,
        )
        snapshot = ProjectSnapshot.objects.create(
            project=self.project,
            name="Ambiguous",
            created_by=self.editor,
        )
        root_entry = ProjectSnapshotEntry.objects.create(
            snapshot=snapshot,
            path="Assembly.FCStd",
            revision=self.assembly_revision,
        )
        ProjectSnapshotEntry.objects.create(
            snapshot=snapshot,
            path="left/Child.FCStd",
            revision=self.child_revision,
        )
        ProjectSnapshotEntry.objects.create(
            snapshot=snapshot,
            path="right/Child.FCStd",
            revision=duplicate_revision,
        )

        tree = assembly_bom_tree(self.assembly_revision)

        self.assertTrue(tree["children"][0]["missing"])
        self.assertEqual(snapshot_entries_with_references(root_entry), [root_entry])

    def test_part_page_contains_drop_zones_slicer_context_and_deep_link(self):
        ManufacturingFile.objects.create(
            revision=self.assembly_revision,
            file_type=ManufacturingFile.FileType.SLICER_PROJECT_3MF,
            file=SimpleUploadedFile("Assembly.3mf", b"3mf"),
            original_filename="Assembly.3mf",
            sha256="b" * 64,
            size_bytes=3,
            uploaded_by=self.editor,
        )
        self.client.force_login(self.editor)

        response = self.client.get(reverse("plm:part_detail", args=[self.assembly.id]))

        self.assertContains(response, 'class="file-drop-zone"', count=2)
        self.assertContains(response, "Slicer-Stand")
        self.assertContains(response, "freecad-plm://revision/")
        self.assertContains(response, "Lebenszyklus")

    def test_editor_can_create_and_list_viewer_annotation(self):
        self.client.force_login(self.editor)
        url = reverse(
            "plm:revision_viewer_annotations", args=[self.assembly_revision.id]
        )

        response = self.client.post(
            url,
            data=json.dumps(
                {
                    "text": "Bohrung prüfen",
                    "viewer_anchor": {"x": 1, "y": 2.5, "z": -3},
                    "viewer_camera": {
                        "position": {"x": 10, "y": 20, "z": 30},
                        "target": {"x": 0, "y": 0, "z": 0},
                    },
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        annotation = Annotation.objects.get()
        self.assertEqual(annotation.viewer_anchor["y"], 2.5)
        listed = self.client.get(url).json()["annotations"]
        self.assertEqual(listed[0]["text"], "Bohrung prüfen")

    def test_viewer_annotation_rejects_reader_and_invalid_anchor(self):
        url = reverse(
            "plm:revision_viewer_annotations", args=[self.assembly_revision.id]
        )
        self.client.force_login(self.reader)
        response = self.client.post(
            url,
            data=json.dumps(
                {"text": "Nicht erlaubt", "viewer_anchor": {"x": 1, "y": 2, "z": 3}}
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.editor)
        response = self.client.post(
            url,
            data=json.dumps({"text": "Ungültig", "viewer_anchor": {"x": 1}}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
