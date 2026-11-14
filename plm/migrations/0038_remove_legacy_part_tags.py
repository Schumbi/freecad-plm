"""Migration 0038 – AP-E2 schema cleanup:

- Remove Part.tags CharField (legacy free-text).
- Rename Part.structured_tags M2M to Part.tags.

Reverse migration:
- Re-creates the CharField and serialises structured tags back as comma-separated string.
- Cannot restore the original byte-for-byte formatting (whitespace, capitalisation
  of duplicate entries), but preserves the full semantic tag set.
"""
from hashlib import sha256

from django.db import migrations, models


def _canonicalise_tags(apps, schema_editor):
    """Ensure Part.structured_tags is populated from the legacy CharField
    for any rows that were written *after* 0037 ran (i.e. during the AP-E2
    deployment window where the application still wrote to the old CharField).
    Already-migrated tags are skipped via ignore_conflicts=True.
    """
    Part = apps.get_model("plm", "Part")
    PartTag = apps.get_model("plm", "PartTag")
    through = Part.structured_tags.through
    database = schema_editor.connection.alias

    for part in Part.objects.using(database).filter(tags__gt="").order_by("pk").iterator():
        for raw in part.tags.split(","):
            name = " ".join(raw.split())
            if not name:
                continue
            identity_hash = sha256(name.casefold().encode("utf-8")).hexdigest()
            tag, _created = PartTag.objects.using(database).get_or_create(
                identity_hash=identity_hash,
                defaults={"name": name},
            )
            through.objects.using(database).get_or_create(
                part_id=part.pk, parttag_id=tag.pk
            )


def _serialise_tags_back(apps, schema_editor):
    Part = apps.get_model("plm", "Part")
    database = schema_editor.connection.alias
    for part in Part.objects.using(database).prefetch_related("structured_tags").iterator(chunk_size=200):
        tags_str = ", ".join(
            part.structured_tags.using(database).order_by("name", "pk").values_list("name", flat=True)
        )
        Part.objects.using(database).filter(pk=part.pk).update(tags=tags_str)


class Migration(migrations.Migration):

    dependencies = [
        ("plm", "0037_migrate_part_tags"),
    ]

    operations = [
        # 1. Final sync pass: pick up any CharField writes since 0037.
        migrations.RunPython(_canonicalise_tags, migrations.RunPython.noop),
        # 2. Remove the legacy CharField.
        migrations.RemoveField(model_name="part", name="tags"),
        # 3. Rename the M2M to "tags".
        migrations.RenameField(model_name="part", old_name="structured_tags", new_name="tags"),
        # Reverse step: re-add CharField, then serialise M2M back into it.
        # (Handled by Django for RemoveField/RenameField reversal; RunPython
        #  below runs only on reverse to populate the CharField.)
        migrations.RunPython(migrations.RunPython.noop, _serialise_tags_back),
    ]
