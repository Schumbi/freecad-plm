from datetime import date, timedelta
from urllib.parse import parse_qs

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Part, Project, ProjectSnapshot
from .services.project_tags import set_project_tags


class ProjectListTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("list-reader")
        self.client.force_login(self.user)
        self.url = reverse("plm:project_list")
        self.a = Project.objects.create(code="A", name="beta", project_date=date(2026, 1, 1))
        self.b = Project.objects.create(code="B", name="Alpha", project_date=date(2026, 2, 1))
        self.c = Project.objects.create(code="C", name="Gamma", project_date=date(2026, 3, 1))
        Project.objects.create(code="ARCHIVE", name="Archived", is_archived=True)
        now = timezone.now()
        for index, project in enumerate([self.b, self.c, self.a]):
            Project.objects.filter(pk=project.pk).update(
                created_at=now + timedelta(days=index), updated_at=now - timedelta(days=index),
            )
        set_project_tags(self.a, ["Werkstatt", "Druck"])
        set_project_tags(self.b, ["Druck"])

    def test_sorting_in_each_view_and_direction(self):
        expected = {"code": [self.a, self.b, self.c], "name": [self.b, self.a, self.c],
                    "created_at": [self.b, self.c, self.a],
                    "updated_at": [self.a, self.c, self.b], "project_date": [self.a, self.b, self.c]}
        for view in ["tiles", "list", "details"]:
            for sort, projects in expected.items():
                for direction in ["asc", "desc"]:
                    with self.subTest(view=view, sort=sort, direction=direction):
                        response = self.client.get(self.url, {"view": view, "sort": sort, "direction": direction})
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(list(response.context["projects"]), projects if direction == "asc" else projects[::-1])

    def test_filtering_with_sorting_and_counts_has_no_duplicates(self):
        for index in range(2):
            Part.objects.create(project=self.a, number=str(index), name="Teil")
        for index in range(3):
            ProjectSnapshot.objects.create(project=self.a, name=str(index), created_by=self.user)
        response = self.client.get(self.url, {"q": "Druck", "view": "details", "sort": "name"})
        projects = list(response.context["projects"])
        self.assertEqual(projects, [self.b, self.a])
        self.assertEqual((projects[1].part_count, projects[1].snapshot_count), (2, 3))
        self.assertContains(response, "Erstellungsdatum")
        self.assertContains(response, "Projektdatum")
        tag = self.a.tags.get(name="Werkstatt")
        response = self.client.get(self.url, {"tag": tag.pk, "view": "list", "sort": "created_at", "direction": "desc"})
        self.assertEqual(list(response.context["projects"]), [self.a])
        self.assertContains(response, 'class="project-compact-list"')
        self.assertContains(response, f'view=list&amp;sort=created_at&amp;direction=desc&amp;tag={tag.pk}')
        response = self.client.get(self.url, {"untagged": "1", "view": "list"})
        self.assertEqual(list(response.context["projects"]), [self.c])

    def test_invalid_preferences_fall_back_and_empty_results_keep_controls(self):
        response = self.client.get(self.url, {"view": "bad", "sort": "tags__name", "direction": "bad", "q": "missing"})
        self.assertEqual(response.context["project_view"], "tiles")
        self.assertEqual(response.context["project_sort"], "code")
        self.assertEqual(response.context["project_direction"], "asc")
        self.assertContains(response, "Keine Projekte gefunden")
        self.assertContains(response, 'id="project-view"')
        self.assertEqual(parse_qs(response.context["presentation_query"]),
                         {"view": ["tiles"], "sort": ["code"], "direction": ["asc"]})

    def test_same_names_have_stable_order_and_details_escape_content(self):
        Project.objects.filter(pk=self.a.pk).update(name=self.b.name, description="<script>alert(1)</script>")
        response = self.client.get(self.url, {"view": "details", "sort": "name"})
        self.assertEqual(list(response.context["projects"]), [self.a, self.b, self.c])
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")

    def test_tag_picker_shows_selection_between_view_and_sort(self):
        tags = list(self.a.tags.values_list("pk", flat=True))
        response = self.client.get(self.url, {"tag": tags, "tag_picker": "1", "view": "details"})
        self.assertEqual(response.context["selected_tag_names"], ["Druck", "Werkstatt"])
        html = response.content.decode()
        self.assertLess(html.index('id="project-view"'), html.index('id="project-tags"'))
        self.assertLess(html.index('id="project-tags"'), html.index('id="project-sort"'))
        self.assertContains(response, 'class="project-tag-picker" open')
        self.assertContains(response, 'id="project-tags-summary">Druck, Werkstatt')
        self.assertNotContains(response, 'Anwenden')
        self.assertNotContains(response, 'project-tag-sidebar')
        self.assertContains(response, 'data-label="Datumsangaben"')
        self.assertContains(response, 'class="project-detail-dates"')
        self.assertEqual(list(response.context["projects"]), [self.a])
        response = self.client.get(self.url, {"tag": tags, "untagged": "1"})
        self.assertContains(response, 'id="project-tags-summary">Ohne Tags')
        self.assertEqual(list(response.context["projects"]), [self.c])
