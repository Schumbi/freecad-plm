from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import ManufacturingFile, Part, Project, Revision
from .permissions import ROLE_ADMIN, ROLE_EDITOR, ROLE_READER


class ManufacturingNavigationTests(TestCase):
    def setUp(self):
        self.users = {}
        for role in (ROLE_READER, ROLE_EDITOR, ROLE_ADMIN):
            group, _ = Group.objects.get_or_create(name=role)
            user = get_user_model().objects.create_user(f"d2-{role}", password="pw")
            user.groups.add(group)
            self.users[role] = user
        self.project = Project.objects.create(code="D2", name="Testprojekt")
        self.with_file = self.make_part("D2-001", "Mit Fertigung")
        self.without_file = self.make_part("D2-002", "Ohne Fertigung")
        self.with_file_revision = self.make_revision(self.with_file, "R0001")
        self.without_file_revision = self.make_revision(self.without_file, "R0001")
        ManufacturingFile.objects.create(
            revision=self.with_file_revision,
            file=SimpleUploadedFile("sample.gcode", b"G1 X0\n"),
            original_filename="sample.gcode", sha256="b" * 64, size_bytes=6,
            uploaded_by=self.users[ROLE_EDITOR], file_type=ManufacturingFile.FileType.GCODE,
        )
        self.search_url = reverse("plm:global_search") + "?q=D2"

    def make_part(self, number, name):
        return Part.objects.create(project=self.project, number=number, name=name)

    def make_revision(self, part, code):
        return Revision.objects.create(
            part=part, revision_code=code,
            file=SimpleUploadedFile(f"{part.number}.step", b"cad"),
            file_format=Revision.FileFormat.STEP,
            original_filename=f"{part.number}.step",
            sha256="a" * 64, size_bytes=3, created_by=self.users[ROLE_EDITOR],
        )

    def test_part_header_link_available_to_all_roles_even_without_files(self):
        for role in (ROLE_READER, ROLE_EDITOR, ROLE_ADMIN):
            self.client.force_login(self.users[role])
            for part in (self.with_file, self.without_file):
                response = self.client.get(reverse("plm:part_detail", args=[part.pk]))
                self.assertEqual(response.status_code, 200)
                header_actions = response.content.decode().split('class="page-header-actions">', 1)[1].split("</div>", 1)[0]
                self.assertIn(reverse("plm:manufacturing_overview", args=[part.pk]), header_actions)
                self.assertIn(">Fertigung</a>", header_actions)

    def test_search_links_only_for_parts_with_manufacturing_files(self):
        self.client.force_login(self.users[ROLE_READER])
        response = self.client.get(self.search_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode().count("<th>Fertigung</th>"), 2)
        url = reverse("plm:manufacturing_overview", args=[self.with_file.pk])
        self.assertContains(response, f'href="{url}" aria-label="Fertigung für D2-001"', count=2)
        self.assertNotContains(response, f'aria-label="Fertigung für D2-002"')
        self.assertEqual(
            [part.has_manufacturing_files for part in response.context["results"].parts],
            [True, False],
        )
        self.assertEqual(
            {rev.part_id: rev.has_manufacturing_files for rev in response.context["results"].revisions},
            {self.with_file.pk: True, self.without_file.pk: False},
        )
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_search_query_count_does_not_grow_with_results(self):
        self.client.force_login(self.users[ROLE_READER])
        with CaptureQueriesContext(connection) as before:
            self.client.get(self.search_url)
        for index in range(3, 9):
            part = self.make_part(f"D2-{index:03d}", f"Testteil {index}")
            revision = self.make_revision(part, "R0001")
            if index % 2:
                ManufacturingFile.objects.create(
                    revision=revision,
                    file=SimpleUploadedFile(f"sample-{index}.gcode", b"G1 X0\n"),
                    original_filename=f"sample-{index}.gcode",
                    sha256=str(index) * 64, size_bytes=6,
                    uploaded_by=self.users[ROLE_EDITOR], file_type=ManufacturingFile.FileType.GCODE,
                )
        with CaptureQueriesContext(connection) as after:
            response = self.client.get(self.search_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(before), len(after))
        self.assertEqual(len(response.context["results"].parts), 8)

    def test_search_requires_login(self):
        response = self.client.get(self.search_url)
        self.assertEqual(response.status_code, 302)
