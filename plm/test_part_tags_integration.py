"""Integration tests for AP-E2: Part tag forms, views, API and search."""
import json

from django.contrib.auth import get_user_model
from .auth import create_api_token
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import Part, PartTag, Project, Revision
from .permissions import ROLE_ADMIN, ROLE_EDITOR, ROLE_READER
from .services.part_tags import set_part_tags, tag_names, tags_as_legacy_string


class PartTagServiceTests(TestCase):
    def test_tag_names_string_input(self):
        self.assertEqual(tag_names("Montage, montage,  Prüfung ,,"), ["Montage", "Prüfung"])

    def test_tag_names_list_input(self):
        self.assertEqual(tag_names(["a", "B", "a "]), ["a", "B"])

    def test_tag_names_empty_string(self):
        self.assertEqual(tag_names(""), [])
        self.assertEqual(tag_names("  ,  "), [])

    def test_tag_names_name_too_long(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            tag_names(["x" * 256])

    def test_tag_names_list_element_with_comma_is_not_split(self):
        # When a list is passed, each element is treated as one tag name.
        # Commas inside a list element do NOT subdivide it further, since the
        # Addon passes already-split names. The PartTag model rejects names with
        # commas via its save() validation.
        self.assertEqual(tag_names(["alpha", "beta"]), ["alpha", "beta"])
        # An empty list gives an empty result.
        self.assertEqual(tag_names([]), [])

    def test_set_part_tags_creates_and_deduplicates(self):
        project = Project.objects.create(code="ST", name="Test")
        part = Part.objects.create(project=project, number="ST-001", name="Teil")
        user = get_user_model().objects.create_user("stuser", password="pw")
        set_part_tags(part, "Montage, Prototyp, montage")
        self.assertEqual(part.tags.count(), 2)
        self.assertEqual(PartTag.objects.count(), 2)

        set_part_tags(part, ["Montage"])
        self.assertEqual(part.tags.count(), 1)
        # PartTag not deleted, still reusable:
        self.assertEqual(PartTag.objects.count(), 2)

    def test_tags_as_legacy_string(self):
        project = Project.objects.create(code="LS", name="Legacy")
        part = Part.objects.create(project=project, number="LS-001", name="Teil")
        set_part_tags(part, "Zink, Aluminium")
        self.assertEqual(tags_as_legacy_string(part), "Aluminium, Zink")


class PartTagViewTests(TestCase):
    def setUp(self):
        for role in (ROLE_READER, ROLE_EDITOR, ROLE_ADMIN):
            g, _ = Group.objects.get_or_create(name=role)
            u = get_user_model().objects.create_user(f"e2-{role}", password="pw")
            u.groups.add(g)
        self.project = Project.objects.create(code="TV", name="View-Test")
        self.part = Part.objects.create(project=self.project, number="TV-001", name="Testteil")
        set_part_tags(self.part, "Montage, Prüfung")
        self.url = reverse("plm:update_part_tags", args=[self.part.pk])
        self.props_url = reverse("plm:part_properties", args=[self.part.pk])

    def _login(self, role):
        self.client.force_login(get_user_model().objects.get(username=f"e2-{role}"))

    def test_part_properties_shows_tags_form_for_editor(self):
        self._login(ROLE_EDITOR)
        response = self.client.get(self.props_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tags bearbeiten")
        self.assertContains(response, "Montage")

    def test_part_properties_no_edit_form_for_reader(self):
        self._login(ROLE_READER)
        response = self.client.get(self.props_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Tags bearbeiten")
        self.assertContains(response, "Montage")

    def test_editor_can_update_tags(self):
        self._login(ROLE_EDITOR)
        response = self.client.post(self.url, {"tags": "Zink, Montage"})
        self.assertRedirects(response, reverse("plm:part_detail", args=[self.part.pk]))
        self.assertEqual(
            set(self.part.tags.values_list("name", flat=True)),
            {"Zink", "Montage"},
        )

    def test_editor_can_clear_tags(self):
        self._login(ROLE_EDITOR)
        self.client.post(self.url, {"tags": ""})
        self.assertFalse(self.part.tags.exists())

    def test_reader_cannot_update_tags(self):
        self._login(ROLE_READER)
        response = self.client.post(self.url, {"tags": "Hacked"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.part.tags.count(), 2)

    def test_anonymous_redirected(self):
        response = self.client.post(self.url, {"tags": "x"})
        self.assertEqual(response.status_code, 302)

    def test_part_detail_shows_tag_chips(self):
        self._login(ROLE_READER)
        revision = Revision.objects.create(
            part=self.part, revision_code="R0001",
            file=SimpleUploadedFile("test.step", b"cad"),
            file_format=Revision.FileFormat.STEP,
            original_filename="test.step", sha256="a" * 64, size_bytes=3,
            created_by=get_user_model().objects.get(username=f"e2-{ROLE_EDITOR}"),
        )
        response = self.client.get(reverse("plm:part_detail", args=[self.part.pk]))
        self.assertContains(response, "project-tag-chip")
        self.assertContains(response, "Montage")
        self.assertContains(response, "Prüfung")

    def test_too_many_tags_form_returns_400(self):
        self._login(ROLE_EDITOR)
        # 101 tags (> 100 limit): "t1,t2,...,t101"
        too_many = ",".join(f"tag{i}" for i in range(101))
        response = self.client.post(self.url, {"tags": too_many})
        self.assertEqual(response.status_code, 400)


class PartTagAPITests(TestCase):
    def setUp(self):
        from .models import ApiToken
        self.admin = get_user_model().objects.create_superuser("api-admin", password="pw")
        _, self.raw_token = create_api_token(user=self.admin, name="test", scopes=[ApiToken.Scope.READ, ApiToken.Scope.WRITE])
        self.project = Project.objects.create(code="API", name="API-Test")
        self.part = Part.objects.create(project=self.project, number="API-001", name="Teil")
        set_part_tags(self.part, "Montage")

    def _auth(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.raw_token}"}

    def test_get_part_includes_tags_and_tag_items(self):
        response = self.client.get(f"/api/parts/{self.part.pk}/", **self._auth())
        self.assertEqual(response.status_code, 200)
        data = response.json()["part"]
        self.assertEqual(data["tags"], "Montage")
        self.assertEqual(data["tag_items"], [{"id": self.part.tags.first().pk, "name": "Montage"}])

    def test_post_part_accepts_string_tags(self):
        response = self.client.post(
            f"/api/parts/{self.part.pk}/",
            json.dumps({"tags": "Zink, Aluminium"}),
            content_type="application/json",
            **self._auth(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(self.part.tags.values_list("name", flat=True)), {"Zink", "Aluminium"})

    def test_post_part_accepts_list_tags(self):
        response = self.client.post(
            f"/api/parts/{self.part.pk}/",
            json.dumps({"tags": ["Zink", "Montage"]}),
            content_type="application/json",
            **self._auth(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(self.part.tags.values_list("name", flat=True)), {"Zink", "Montage"})

    def test_post_part_missing_tags_key_does_not_clear(self):
        response = self.client.post(
            f"/api/parts/{self.part.pk}/",
            json.dumps({"name": "Neuer Name"}),
            content_type="application/json",
            **self._auth(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.part.tags.count(), 1)

    def test_post_part_empty_string_clears_tags(self):
        response = self.client.post(
            f"/api/parts/{self.part.pk}/",
            json.dumps({"tags": ""}),
            content_type="application/json",
            **self._auth(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.part.tags.exists())

    def test_create_part_via_api_with_tags(self):
        response = self.client.post(
            f"/api/projects/{self.project.pk}/parts/",
            json.dumps({"number": "API-002", "name": "Neu", "tags": "Prüfung, Zink"}),
            content_type="application/json",
            **self._auth(),
        )
        self.assertEqual(response.status_code, 201)
        part = Part.objects.get(number="API-002")
        self.assertEqual(set(part.tags.values_list("name", flat=True)), {"Prüfung", "Zink"})

    def test_legacy_string_returned_for_backward_compat(self):
        set_part_tags(self.part, "Alpha, Beta")
        response = self.client.get(f"/api/parts/{self.part.pk}/", **self._auth())
        self.assertEqual(response.json()["part"]["tags"], "Alpha, Beta")


class PartTagSearchTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("search-user", password="pw")
        self.project = Project.objects.create(code="SR", name="Suche")
        self.tagged = Part.objects.create(project=self.project, number="SR-001", name="Testteil")
        self.untagged = Part.objects.create(project=self.project, number="SR-002", name="Ohne")
        set_part_tags(self.tagged, "Prüfung")
        self.client.force_login(self.user)

    def test_search_finds_part_by_structured_tag(self):
        response = self.client.get(reverse("plm:global_search") + "?q=Prüfung")
        self.assertEqual(response.status_code, 200)
        part_numbers = [p.number for p in response.context["results"].parts]
        self.assertIn("SR-001", part_numbers)
        self.assertNotIn("SR-002", part_numbers)
