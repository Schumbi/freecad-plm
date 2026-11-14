"""Regressionsschutz fuer die UX-/Accessibility-Massnahmen (Audit 2026-11-14)."""

import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Part, Project, Revision


class AccessibilityRegressionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(
            "ux-a11y", "ux@example.test", "pw"
        )
        cls.project = Project.objects.create(code="A11Y", name="Barrierefrei")
        cls.part = Part.objects.create(
            project=cls.project,
            number="P-100",
            name="Prüfteil",
            category=Part.Category.PART,
        )
        Revision.objects.create(
            part=cls.part,
            revision_code="R0001",
            status=Revision.Status.DRAFT,
            file="revisions/test.step",
            file_format=Revision.FileFormat.STEP,
            original_filename="test.step",
            sha256="a" * 64,
            size_bytes=1,
            created_by=cls.user,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_pages_have_descriptive_titles(self):
        cases = [
            (reverse("plm:project_list"), "Projekte · FreeCAD-PLM"),
            (reverse("plm:project_detail", args=[self.project.id]),
             "A11Y · Barrierefrei · FreeCAD-PLM"),
            (reverse("plm:part_detail", args=[self.part.id]),
             "P-100 · Prüfteil · FreeCAD-PLM"),
        ]
        for url, title in cases:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, f"<title>{title}</title>", html=False)

    def test_active_navigation_item_is_marked(self):
        response = self.client.get(
            reverse("plm:project_detail", args=[self.project.id])
        )
        self.assertContains(
            response,
            'class="active" aria-current="page"',
            count=1,
        )

    def test_skip_link_and_main_target_exist(self):
        response = self.client.get(reverse("plm:project_list"))
        self.assertContains(response, 'class="skip-link" href="#main"')
        self.assertContains(response, 'id="main"')

    def test_error_message_is_announced(self):
        response = self.client.post(
            reverse("plm:delete_project", args=[self.project.id]),
            {"confirmation": "FALSCH"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'role="alert"', count=1, status_code=400)
        self.assertContains(
            response,
            "Der eingegebene Projektcode stimmt nicht.",
            status_code=400,
        )

    def test_part_rows_expose_real_links(self):
        response = self.client.get(
            reverse("plm:project_detail", args=[self.project.id])
        )
        self.assertContains(
            response,
            f'href="{reverse("plm:part_detail", args=[self.part.id])}"',
        )
        self.assertNotContains(response, "onclick=\"window.location=")

    def test_part_detail_has_unique_element_ids(self):
        response = self.client.get(reverse("plm:part_detail", args=[self.part.id]))
        html = response.content.decode()
        ids = re.findall(r'\bid="([^"]+)"', html)
        duplicates = {value for value in ids if ids.count(value) > 1}
        self.assertEqual(duplicates, set())

    def test_search_page_has_only_one_query_field(self):
        response = self.client.get(reverse("plm:global_search"), {"q": "test"})
        html = response.content.decode()
        self.assertEqual(html.count('type="search"'), 1)
        self.assertEqual(html.count('name="q"'), 2)  # sichtbares Suchfeld + Hidden-Feld im Filterformular

    def test_unknown_tag_filter_is_explained(self):
        response = self.client.get(reverse("plm:project_list"), {"tag": "999999"})
        self.assertContains(response, "Unbekannter Tag (999999)")
        self.assertContains(response, "Filter zurücksetzen")

    def test_contrast_tokens_meet_aa(self):
        css = Path(settings.BASE_DIR, "plm", "static", "plm", "app.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("--accent: #0f766e;", css)
        self.assertIn("--muted: #5b6472;", css)
