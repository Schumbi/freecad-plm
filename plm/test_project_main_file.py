from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .auth import create_api_token
from .forms import ProjectForm
from .models import ApiToken, Part, Project, Revision


class ProjectMainFileTests(TestCase):
    def setUp(self):
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        override = override_settings(MEDIA_ROOT=self.media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.admin = get_user_model().objects.create_superuser(username="main-admin", password="test")
        self.project = Project.objects.create(code="MAIN", name="Main project")
        self.main = Part.objects.create(project=self.project, number="A", name="Assembly")
        self.other = Part.objects.create(project=self.project, number="B", name="Other")
        self.revision(self.main, "Assembly.FCStd", "R0001")
        self.revision(self.other, "Other.step", "R0001", Revision.FileFormat.STEP)
        _, token = create_api_token(user=self.admin, name="admin", scopes=[ApiToken.Scope.ADMIN])
        self.auth = {"HTTP_AUTHORIZATION": "Bearer " + token}

    def revision(self, part, filename, code, file_format=Revision.FileFormat.FCSTD):
        return Revision.objects.create(
            part=part, revision_code=code, file_format=file_format,
            original_filename=filename, file=SimpleUploadedFile(filename, b"cad"),
            sha256="a" * 64, size_bytes=3, created_by=self.admin,
        )

    def test_web_selection_and_new_revision(self):
        self.client.force_login(self.admin)
        form = ProjectForm(instance=self.project)
        self.assertEqual(list(form.fields["main_part"].queryset), [self.main])
        response = self.client.post(reverse("plm:edit_project", args=[self.project.pk]), {
            "code": "MAIN", "name": "Main project", "status": "running",
            "project_date": str(self.project.project_date), "description": "",
            "main_part": self.main.pk,
        })
        self.assertEqual(response.status_code, 302)
        response = self.client.get(reverse("plm:project_detail", args=[self.project.pk]))
        self.assertContains(response, "Assembly.FCStd")
        self.assertContains(response, 'id="other-project-files"')
        self.assertNotContains(response, 'id="other-project-files" open')
        self.revision(self.main, "Assembly-v2.FCStd", "R0002")
        response = self.client.get(reverse("plm:project_detail", args=[self.project.pk]))
        self.assertContains(response, "Assembly-v2.FCStd")

    def test_api_rejects_wrong_project_non_fcstd_and_reader(self):
        url = f"/api/projects/{self.project.pk}/"
        other_project = Project.objects.create(code="OTHER", name="Other project")
        external = Part.objects.create(project=other_project, number="X", name="External")
        self.revision(external, "External.FCStd", "R0001")
        for part_id in (self.other.pk, external.pk, True, "1"):
            response = self.client.post(url, {"main_part_id": part_id}, content_type="application/json", **self.auth)
            self.assertEqual(response.status_code, 400)
        response = self.client.post(url, {"main_part_id": self.main.pk}, content_type="application/json", **self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["project"]["main_part_id"], self.main.pk)
        parts = self.client.get(f"/api/projects/{self.project.pk}/parts/", **self.auth).json()["parts"]
        self.assertEqual(parts[0]["latest_fcstd_revision"]["original_filename"], "Assembly.FCStd")
        self.assertIsNone(parts[1]["latest_fcstd_revision"])
        self.main.is_archived = True
        self.main.save()
        self.project.refresh_from_db()
        self.assertIsNone(self.project.main_part_id)

    def test_unconfigured_project_keeps_existing_list(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("plm:project_detail", args=[self.project.pk]))
        self.assertNotContains(response, 'id="other-project-files"')
        self.assertContains(response, 'id="part-list"')
