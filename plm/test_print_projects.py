import json
import tempfile
from io import BytesIO
from zipfile import ZipFile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .auth import create_api_token
from .models import ApiToken, Part, PrintProject, Project, Revision
from .permissions import ROLE_EDITOR


def bambu_project_upload():
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("3D/3dmodel.model", "<model><resources/><build/></model>")
        archive.writestr("Metadata/plate_1.json", json.dumps({"name": "Mount und Figur"}))
        archive.writestr("Metadata/plate_1.png", b"plate-one")
        archive.writestr("Metadata/plate_2.json", json.dumps({"plate_name": "Reserve"}))
    return SimpleUploadedFile("druckprojekt.3mf", buffer.getvalue(), content_type="application/octet-stream")


class PrintProjectViewTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_root.cleanup)
        media_override = self.settings(MEDIA_ROOT=self.media_root.name)
        media_override.enable()
        self.addCleanup(media_override.disable)
        self.user = get_user_model().objects.create_user(username="print-editor")
        self.user.groups.add(Group.objects.get_or_create(name=ROLE_EDITOR)[0])
        self.project = Project.objects.create(code="P-PRINT", name="Druckprojekt")
        part = Part.objects.create(project=self.project, number="A-001", name="Mount")
        self.revision = Revision.objects.create(
            part=part,
            revision_code="R0001",
            file=SimpleUploadedFile("Mount.FCStd", b"fcstd"),
            original_filename="Mount.FCStd",
            sha256="a" * 64,
            size_bytes=5,
            created_by=self.user,
        )

    def create_print_project(self):
        _, token = create_api_token(
            user=self.user,
            name="print-project-test",
            scopes=[ApiToken.Scope.READ, ApiToken.Scope.WRITE],
        )
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        response = self.client.post(
            reverse("plm:api_print_projects"),
            data=json.dumps({"revision_id": self.revision.id, "code": "DP-1", "name": "Gemischte Platte"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        return response.json()["print_project"]["id"]

    def test_3mf_plates_are_extracted_and_external_stl_can_be_added_in_web_ui(self):
        print_project_id = self.create_print_project()
        response = self.client.post(
            reverse("plm:api_print_project_slicer", args=[print_project_id]),
            {"file": bambu_project_upload()},
        )
        self.assertEqual(response.status_code, 200)
        print_project = PrintProject.objects.get(id=print_project_id)
        self.assertEqual(list(print_project.plates.values_list("name", flat=True)), ["Mount und Figur", "Reserve"])
        self.assertTrue(print_project.plates.first().preview)

        self.client.defaults.pop("HTTP_AUTHORIZATION")
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("plm:upload_print_project_source", args=[print_project_id]),
            {"label": "Figur", "file": SimpleUploadedFile("figur.stl", b"solid figur\nendsolid\n")},
        )
        self.assertRedirects(response, reverse("plm:project_detail", args=[self.project.id]))
        response = self.client.get(reverse("plm:project_detail", args=[self.project.id]))
        self.assertContains(response, "Mount und Figur")
        self.assertContains(response, "STL hinzufügen")
        self.assertContains(response, "Figur")
