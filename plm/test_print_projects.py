import json
import tempfile
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .auth import create_api_token
from .models import (
    ApiToken,
    AuditEvent,
    Part,
    PrintProject,
    PrintProjectSnapshot,
    Project,
    Revision,
)
from .permissions import ROLE_EDITOR


def bambu_project_upload():
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "3D/3dmodel.model",
            '<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
            '<resources><object id="1" type="model"><mesh><vertices>'
            '<vertex x="0" y="0" z="0"/><vertex x="10" y="0" z="0"/>'
            '<vertex x="0" y="10" z="0"/></vertices><triangles>'
            '<triangle v1="0" v2="1" v3="2"/></triangles></mesh></object></resources>'
            '<build><item objectid="1"/></build></model>',
        )
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

    def test_preview_api_requires_token_and_returns_plate_image(self):
        project_id = self.create_print_project()
        response = self.client.post(
            reverse("plm:api_print_project_slicer", args=[project_id]),
            {"file": bambu_project_upload()},
        )
        plates = response.json()["print_project"]["plates"]
        url = next(plate["preview_url"] for plate in plates if plate["has_preview"])
        self.assertTrue(any(plate["preview_url"] is None for plate in plates))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(b"".join(response.streaming_content), b"plate-one")
        response.close()
        self.client.defaults.pop("HTTP_AUTHORIZATION")
        self.assertEqual(self.client.get(url).status_code, 401)

    def test_require_new_rejects_existing_code_without_changing_project(self):
        project_id = self.create_print_project()
        response = self.client.post(
            reverse("plm:api_print_projects"),
            data=json.dumps({"revision_id": self.revision.id, "code": "DP-1",
                             "name": "Replacement", "require_new": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(PrintProject.objects.get(pk=project_id).name, "Gemischte Platte")
        self.assertEqual(PrintProject.objects.count(), 1)

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
        self.assertContains(response, 'data-dialog-target="#print-projects"')
        self.assertContains(response, 'id="print-projects"')
        self.assertContains(response, "Mount und Figur")
        self.assertContains(response, "STL hinzufügen")
        self.assertContains(response, "Figur")

    def test_plm_revision_can_be_added_as_print_project_source(self):
        print_project_id = self.create_print_project()
        second_part = Part.objects.create(
            project=self.project, number="A-002", name="Scheibe"
        )
        second_revision = Revision.objects.create(
            part=second_part,
            revision_code="R0001",
            file=SimpleUploadedFile("Scheibe.FCStd", b"fcstd"),
            original_filename="Scheibe.FCStd",
            sha256="b" * 64,
            size_bytes=5,
            created_by=self.user,
        )

        response = self.client.post(
            reverse("plm:api_print_project_source", args=[print_project_id]),
            data=json.dumps(
                {"revision_id": second_revision.id, "label": "Scheibe R0001"}
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["source"]["revision_id"], second_revision.id)
        self.assertEqual(response.json()["source"]["label"], "Scheibe R0001")
        print_project = PrintProject.objects.get(id=print_project_id)
        self.assertTrue(print_project.sources.filter(revision=second_revision).exists())

    def test_logged_in_user_can_download_print_project_from_web_ui(self):
        print_project_id = self.create_print_project()
        upload = bambu_project_upload()
        expected_content = upload.read()
        upload.seek(0)
        response = self.client.post(
            reverse("plm:api_print_project_slicer", args=[print_project_id]),
            {"file": upload},
        )
        self.assertEqual(response.status_code, 200)

        self.client.defaults.pop("HTTP_AUTHORIZATION")
        download_url = reverse(
            "plm:download_print_project_slicer", args=[print_project_id]
        )
        response = self.client.get(download_url)
        self.assertRedirects(response, f"{reverse('plm:login')}?next={download_url}")

        self.client.force_login(self.user)
        project_response = self.client.get(
            reverse("plm:project_detail", args=[self.project.id])
        )
        self.assertContains(project_response, download_url)
        self.assertContains(project_response, "3MF herunterladen")
        self.assertContains(project_response, "Unterseite in 3D")
        self.assertContains(project_response, f'data-model-viewer-source="{download_url}"')
        self.assertContains(project_response, 'data-model-viewer-view="bottom"')
        self.assertContains(project_response, 'id="model-viewer-bottom"')

        part_response = self.client.get(
            reverse("plm:part_detail", args=[self.revision.part_id])
        )
        self.assertContains(part_response, "Druckprojekt DP-1")
        self.assertContains(part_response, "Druckprojekte")
        self.assertContains(part_response, download_url)
        self.assertContains(part_response, "Unterseite in 3D")

        response = self.client.get(download_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), expected_content)
        self.assertEqual(
            response.headers["Content-Disposition"],
            'attachment; filename="druckprojekt.3mf"',
        )

    def test_revision_from_another_project_is_rejected_as_print_source(self):
        print_project_id = self.create_print_project()
        other_project = Project.objects.create(code="OTHER", name="Anderes Projekt")
        other_part = Part.objects.create(
            project=other_project, number="X-001", name="Fremdteil"
        )
        other_revision = Revision.objects.create(
            part=other_part,
            revision_code="R0001",
            file=SimpleUploadedFile("Fremd.FCStd", b"fcstd"),
            original_filename="Fremd.FCStd",
            sha256="c" * 64,
            size_bytes=5,
            created_by=self.user,
        )

        response = self.client.post(
            reverse("plm:api_print_project_source", args=[print_project_id]),
            data=json.dumps({"revision_id": other_revision.id}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 409)


    def test_admin_can_delete_print_project_and_stored_files(self):
        print_project_id = self.create_print_project()
        response = self.client.post(
            reverse("plm:api_print_project_slicer", args=[print_project_id]),
            {"file": bambu_project_upload()},
        )
        self.assertEqual(response.status_code, 200)
        print_project = PrintProject.objects.get(id=print_project_id)
        source = print_project.sources.create(
            source_type="external_stl",
            file=SimpleUploadedFile("figure.stl", b"solid figure\nendsolid\n"),
            original_filename="figure.stl",
            sha256="d" * 64,
            size_bytes=23,
            uploaded_by=self.user,
        )
        stored_paths = [
            print_project.slicer_file.path,
            source.file.path,
            print_project.plates.get(plate_number=1).preview.path,
        ]
        self.client.defaults.pop("HTTP_AUTHORIZATION")
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.client.force_login(self.user)

        project_page = self.client.get(
            reverse("plm:project_detail", args=[self.project.id])
        )
        delete_url = reverse("plm:delete_print_project", args=[print_project_id])
        self.assertContains(project_page, delete_url)
        confirmation = self.client.get(delete_url)
        self.assertContains(confirmation, "Druckprojekt dauerhaft löschen")

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(delete_url)

        self.assertRedirects(
            response,
            reverse("plm:project_detail", args=[self.project.id]),
        )
        self.assertFalse(PrintProject.objects.filter(id=print_project_id).exists())
        self.assertTrue(all(not Path(path).exists() for path in stored_paths))
        event = AuditEvent.objects.get(action=AuditEvent.Action.PRINT_PROJECT_DELETED)
        self.assertEqual(event.metadata["code"], "DP-1")
        self.assertEqual(event.metadata["source_count"], 2)

    def test_print_project_with_snapshot_cannot_be_deleted(self):
        print_project_id = self.create_print_project()
        print_project = PrintProject.objects.get(id=print_project_id)
        PrintProjectSnapshot.objects.create(
            print_project=print_project,
            file=SimpleUploadedFile("snapshot.3mf", b"snapshot"),
            original_filename="snapshot.3mf",
            sha256="e" * 64,
            size_bytes=8,
            bambuddy_archive_id=24,
            created_by=self.user,
        )
        self.client.defaults.pop("HTTP_AUTHORIZATION")
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.client.force_login(self.user)
        delete_url = reverse("plm:delete_print_project", args=[print_project_id])

        confirmation = self.client.get(delete_url)
        self.assertContains(confirmation, "kann deshalb nicht gelöscht werden")
        self.assertNotContains(confirmation, "Druckprojekt dauerhaft löschen")
        response = self.client.post(delete_url, follow=True)

        self.assertContains(response, "gespeicherte Druck-Snapshots")
        self.assertTrue(PrintProject.objects.filter(id=print_project_id).exists())

    def test_editor_cannot_delete_print_project(self):
        print_project_id = self.create_print_project()
        self.client.defaults.pop("HTTP_AUTHORIZATION")
        self.client.force_login(self.user)
        delete_url = reverse("plm:delete_print_project", args=[print_project_id])

        page = self.client.get(reverse("plm:project_detail", args=[self.project.id]))
        self.assertNotContains(page, delete_url)
        response = self.client.post(delete_url)

        self.assertEqual(response.status_code, 403)
        self.assertTrue(PrintProject.objects.filter(id=print_project_id).exists())
