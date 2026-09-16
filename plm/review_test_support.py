"""Small real file fixtures shared by regression and addon contract tests."""
import json
from io import BytesIO
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile

from .auth import create_api_token
from .models import ApiToken, Part, PrintProject, Project, Revision
from .permissions import ROLE_EDITOR


def mesh_upload(*, marker="first", geometry=True):
    model = '''<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" unit="millimeter">
      <resources><object id="1" type="model"><mesh><vertices>
      <vertex x="0" y="0" z="0"/><vertex x="10" y="0" z="0"/>
      <vertex x="0" y="10" z="0"/></vertices><triangles>
      <triangle v1="0" v2="1" v3="2"/></triangles></mesh></object></resources>
      <build><item objectid="1"/></build></model>'''
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("3D/3dmodel.model", model if geometry else "<model><resources/><build/></model>")
        archive.writestr("Metadata/plate_1.json", json.dumps({"name": marker}))
        archive.writestr("Metadata/plate_1.png", b"preview-" + marker.encode())
    return SimpleUploadedFile("project.3mf", buffer.getvalue(), content_type="model/3mf")


class PrintProjectFixture:
    def setUp(self):
        super().setUp()
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.media_root = temporary.name
        setting = self.settings(MEDIA_ROOT=self.media_root)
        setting.enable()
        self.addCleanup(setting.disable)
        self.user = get_user_model().objects.create_user(username="regression-editor")
        self.user.groups.add(Group.objects.get_or_create(name=ROLE_EDITOR)[0])
        self.project = Project.objects.create(code="REGRESSION", name="Regression")
        self.revision = self.make_revision(self.project, "A-001")
        self.token, self.raw_token = create_api_token(
            user=self.user, name="regression", scopes=[ApiToken.Scope.READ, ApiToken.Scope.WRITE]
        )
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {self.raw_token}"
        self.item = PrintProject.objects.create(
            project=self.project, primary_revision=self.revision, code="DP-1", name="Plate"
        )
        self.url = f"/api/print-projects/{self.item.pk}/slicer-project/"

    def make_revision(self, project, number):
        part = Part.objects.create(project=project, number=number, name=number)
        return Revision.objects.create(
            part=part, revision_code="R0001", file=SimpleUploadedFile("model.FCStd", b"fixture"),
            original_filename="model.FCStd", sha256="a" * 64, size_bytes=7, created_by=self.user
        )

    def upload(self, *, marker="first", **fields):
        return self.client.post(self.url, {"file": mesh_upload(marker=marker), **fields})

    def initial_upload(self):
        response = self.upload(base_sha256="")
        self.assertEqual(response.status_code, 200, response.content)
        self.item.refresh_from_db()
        return self.item.slicer_sha256
