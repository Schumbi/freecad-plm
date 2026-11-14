from hashlib import sha256

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class PartTagMigrationTests(TransactionTestCase):
    migrate_from = ("plm", "0035_projectdocumentversion_note_projectdocumentfolder")
    migrate_to = ("plm", "0037_migrate_part_tags")

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.migrate([target])
        return executor.loader.project_state([target]).apps

    def setUp(self):
        old_apps = self.migrate(self.migrate_from)
        Project = old_apps.get_model("plm", "Project")
        Part = old_apps.get_model("plm", "Part")
        project = Project.objects.create(code="TAG", name="Tag-Migration")
        self.original = {
            "first": " Montage ,montage,  Äußeres   & Prüfung ,, ",
            "second": "MONTAGE, Café, Cafe\u0301, <script>x</script>, x  y",
            "long": "L" * 200,
            "empty": " , \t,",
        }
        self.part_ids = {
            key: Part.objects.create(
                project=project,
                number=f"P-{index:03d}",
                name=key,
                tags=value,
            ).pk
            for index, (key, value) in enumerate(self.original.items(), start=1)
        }

    def tearDown(self):
        self.migrate(self.migrate_to)

    def test_forward_and_backward_data_migration(self):
        apps = self.migrate(self.migrate_to)
        Part = apps.get_model("plm", "Part")
        PartTag = apps.get_model("plm", "PartTag")

        first = Part.objects.get(pk=self.part_ids["first"])
        second = Part.objects.get(pk=self.part_ids["second"])
        long_part = Part.objects.get(pk=self.part_ids["long"])
        empty = Part.objects.get(pk=self.part_ids["empty"])

        self.assertEqual(
            set(first.structured_tags.values_list("name", flat=True)),
            {"Montage", "Äußeres & Prüfung"},
        )
        self.assertEqual(
            set(second.structured_tags.values_list("name", flat=True)),
            {"Montage", "Café", "Cafe\u0301", "<script>x</script>", "x y"},
        )
        self.assertEqual(
            list(long_part.structured_tags.values_list("name", flat=True)),
            ["L" * 200],
        )
        self.assertFalse(empty.structured_tags.exists())
        self.assertEqual(PartTag.objects.count(), 7)
        montage = PartTag.objects.get(name="Montage")
        self.assertEqual(
            montage.identity_hash,
            sha256("montage".encode("utf-8")).hexdigest(),
        )

        reverse_apps = self.migrate(("plm", "0036_add_structured_part_tags"))
        ReversePart = reverse_apps.get_model("plm", "Part")
        ReversePartTag = reverse_apps.get_model("plm", "PartTag")
        self.assertFalse(ReversePartTag.objects.exists())
        for key, part_id in self.part_ids.items():
            part = ReversePart.objects.get(pk=part_id)
            self.assertEqual(part.tags, self.original[key])
            self.assertFalse(part.structured_tags.exists())
