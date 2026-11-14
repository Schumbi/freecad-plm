from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import ManufacturingFile, Part, Project, Revision
from .permissions import ROLE_ADMIN, ROLE_EDITOR, ROLE_READER


class ManufacturingOverviewTests(TestCase):
    def setUp(self):
        self.users = {}
        for role in (ROLE_READER, ROLE_EDITOR, ROLE_ADMIN):
            group, _ = Group.objects.get_or_create(name=role)
            user = get_user_model().objects.create_user(f"d1-{role}", password="pw")
            user.groups.add(group)
            self.users[role] = user
        self.part = Part.objects.create(
            project=Project.objects.create(code="D1", name="Testprojekt"),
            number="D1-001", name="Testteil",
        )
        self.other_part = Part.objects.create(
            project=self.part.project, number="D1-002", name="Fremdteil",
        )
        self.revision = self.make_revision(self.part, "R0001")
        self.old_revision = self.make_revision(self.part, "R0000", Revision.Status.OBSOLETE)
        self.foreign_revision = self.make_revision(self.other_part, "R0001")
        self.url = reverse("plm:manufacturing_overview", args=[self.part.pk])

    def make_revision(self, part, code, status=Revision.Status.DRAFT):
        return Revision.objects.create(
            part=part, revision_code=code, status=status,
            file=SimpleUploadedFile(f"{code}.step", b"cad"),
            file_format=Revision.FileFormat.STEP, original_filename=f"{code}.step",
            sha256="a" * 64, size_bytes=3, created_by=self.users[ROLE_EDITOR],
        )

    def make_file(self, revision, name, file_type):
        return ManufacturingFile.objects.create(
            revision=revision, file=SimpleUploadedFile(name, b"data"),
            original_filename=name, sha256=(name[0] * 64)[:64],
            size_bytes=4, uploaded_by=self.users[ROLE_EDITOR], file_type=file_type,
        )

    def test_reader_can_view_all_revisions_but_not_upload_or_delete(self):
        current = self.make_file(self.revision, "current.gcode", ManufacturingFile.FileType.GCODE)
        old = self.make_file(self.old_revision, "old.pdf", ManufacturingFile.FileType.PDF_DRAWING)
        self.make_file(self.foreign_revision, "foreign.stl", ManufacturingFile.FileType.STL_PRINT)
        self.client.force_login(self.users[ROLE_READER])
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, current.original_filename)
        self.assertContains(response, old.original_filename)
        self.assertNotContains(response, "foreign.stl")
        self.assertNotContains(response, 'name="revision" required')
        self.assertNotContains(response, reverse("plm:delete_manufacturing_file", args=[current.pk]))
        response = self.client.post(self.url, {"revision": self.revision.pk})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ManufacturingFile.objects.filter(revision__part=self.part).count(), 2)

    def test_editor_upload_and_validation(self):
        self.client.force_login(self.users[ROLE_EDITOR])
        response = self.client.post(self.url, {
            "revision": self.revision.pk, "purpose": ManufacturingFile.Purpose.PRINT,
            "file": SimpleUploadedFile("new.gcode", b"G1 X0\n"),
        })
        self.assertRedirects(response, self.url)
        item = ManufacturingFile.objects.get(revision=self.revision)
        self.assertEqual(item.file_type, ManufacturingFile.FileType.GCODE)
        self.assertEqual(item.uploaded_by, self.users[ROLE_EDITOR])
        self.assertNotContains(self.client.get(self.url), reverse("plm:delete_manufacturing_file", args=[item.pk]))

        for revision_id in (self.old_revision.pk, self.foreign_revision.pk, "invalid"):
            response = self.client.post(self.url, {
                "revision": revision_id, "purpose": ManufacturingFile.Purpose.PRINT,
                "file": SimpleUploadedFile("another.gcode", b"G1 X1\n"),
            })
            self.assertEqual(response.status_code, 400)
            self.assertContains(response, "Bitte eine aktive Revision dieses Teils auswählen.", status_code=400)
        self.assertEqual(ManufacturingFile.objects.count(), 1)

    def test_no_active_revision_rejects_upload(self):
        self.revision.status = Revision.Status.OBSOLETE
        self.revision.save()
        self.client.force_login(self.users[ROLE_EDITOR])
        response = self.client.post(self.url, {
            "revision": self.revision.pk, "purpose": ManufacturingFile.Purpose.PRINT,
            "file": SimpleUploadedFile("new.gcode", b"G1 X0\n"),
        })
        self.assertContains(response, "Keine aktive Revision vorhanden", status_code=400)
        self.assertEqual(ManufacturingFile.objects.count(), 0)

    def test_filters_sort_and_admin_delete_link(self):
        first = self.make_file(self.old_revision, "old.pdf", ManufacturingFile.FileType.PDF_DRAWING)
        second = self.make_file(self.revision, "new.gcode", ManufacturingFile.FileType.GCODE)
        self.client.force_login(self.users[ROLE_ADMIN])
        response = self.client.get(self.url, {"revision": str(self.revision.pk), "type": "gcode"})
        self.assertContains(response, second.original_filename)
        self.assertNotContains(response, first.original_filename)
        self.assertContains(response, reverse("plm:delete_manufacturing_file", args=[second.pk]))
        response = self.client.get(self.url, {"type": "invalid", "sort": "oldest"})
        self.assertEqual(list(response.context["manufacturing_files"]), [first, second])
        self.assertEqual(response.context["selected_type"], "")

    def test_anonymous_redirects(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
