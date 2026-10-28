import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .auth import create_api_token
from .models import ApiToken, Project, ProjectFolder


class ProjectFolderApiTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username="folder-admin", password="test")
        _, token = create_api_token(user=self.admin, name="test", scopes=[ApiToken.Scope.ADMIN])
        self.auth = {"HTTP_AUTHORIZATION": "Bearer " + token}

    def post_json(self, url, data):
        return self.client.post(url, json.dumps(data), content_type="application/json", **self.auth)

    def test_hierarchy_and_protected_deletion(self):
        root = self.post_json("/api/folders/", {"name": "Root"}).json()["folder"]
        child = self.post_json("/api/folders/", {"name": "Child", "parent_id": root["id"]}).json()["folder"]
        self.assertEqual(self.post_json(f'/api/folders/{root["id"]}/', {"parent_id": child["id"]}).status_code, 400)
        self.assertEqual(self.client.delete(f'/api/folders/{root["id"]}/', **self.auth).status_code, 409)
        self.assertEqual(self.post_json("/api/folders/", {"name": "Root"}).status_code, 400)
        Project.objects.create(code="P", name="Project", folder_id=child["id"])
        self.assertEqual(self.client.delete(f'/api/folders/{child["id"]}/', **self.auth).status_code, 409)

    def test_legacy_update_preserves_folder_and_filter(self):
        folder = ProjectFolder.objects.create(name="Test")
        project = Project.objects.create(code="P", name="Project", folder=folder)
        Project.objects.create(code="Q", name="Other")
        response = self.post_json(f"/api/projects/{project.pk}/", {"name": "Changed"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["project"]["folder_id"], folder.pk)
        response = self.client.get("/api/projects/", {"folder": folder.pk}, **self.auth)
        self.assertEqual([p["id"] for p in response.json()["projects"]], [project.pk])
        self.assertEqual(self.post_json(f"/api/projects/{project.pk}/", {"folder_id": None}).status_code, 200)
        project.refresh_from_db()
        self.assertIsNone(project.folder_id)

    def test_reader_cannot_manage_folders(self):
        reader = get_user_model().objects.create_user(username="reader")
        _, token = create_api_token(user=reader, name="read", scopes=[ApiToken.Scope.READ])
        auth = {"HTTP_AUTHORIZATION": "Bearer " + token}
        self.assertEqual(self.client.get("/api/folders/", **auth).status_code, 200)
        self.assertEqual(self.client.post("/api/folders/", "{}", content_type="application/json", **auth).status_code, 403)

    def test_web_tree_filters_direct_projects_and_admin_move(self):
        parent = ProjectFolder.objects.create(name="Parent")
        child = ProjectFolder.objects.create(name="Child", parent=parent)
        direct = Project.objects.create(code="A", name="Direct", folder=parent)
        Project.objects.create(code="B", name="Nested", folder=child)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("plm:project_list"), {"folder": parent.pk})
        self.assertEqual([p.code for p in response.context["projects"]], ["A"])
        self.assertContains(response, "Child")
        self.assertEqual(response.context["selected_folder_label"], "Parent")
        self.assertContains(response, 'class="project-folder-picker"')
        self.assertContains(response, 'id="project-folder-summary">Parent</span>')
        self.assertNotContains(response, 'grid-template-columns:minmax(12rem,18rem)')
        response = self.client.get(reverse("plm:project_list"), {"folder": child.pk})
        self.assertEqual(response.context["selected_folder_label"], "Parent / Child")
        response = self.client.post(reverse("plm:manage_project_folders"),
            {"action": "move_project", "project_id": direct.pk, "parent_id": child.pk})
        self.assertEqual(response.status_code, 302)
        direct.refresh_from_db()
        self.assertEqual(direct.folder_id, child.pk)
        response = self.client.post(reverse("plm:manage_project_folders"),
            {"action": "update", "folder_id": parent.pk, "name": "Parent", "parent_id": child.pk})
        self.assertEqual(response.status_code, 400)

    def test_reader_web_folder_management_forbidden(self):
        reader = get_user_model().objects.create_user(username="reader-web")
        self.client.force_login(reader)
        self.assertEqual(self.client.get(reverse("plm:manage_project_folders")).status_code, 403)
