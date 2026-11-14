from hashlib import sha256

from django.db import migrations


def normalized_name(raw):
    return " ".join(raw.split())


def migrate_part_tags(apps, schema_editor):
    Part = apps.get_model("plm", "Part")
    PartTag = apps.get_model("plm", "PartTag")
    through = Part.structured_tags.through
    database = schema_editor.connection.alias
    tags_by_hash = {}
    assignments = []

    for part in Part.objects.using(database).order_by("pk").iterator():
        seen = set()
        for raw_name in part.tags.split(","):
            name = normalized_name(raw_name)
            if not name:
                continue
            identity = name.casefold()
            identity_hash = sha256(identity.encode("utf-8")).hexdigest()
            if identity_hash in seen:
                continue
            seen.add(identity_hash)

            tag = tags_by_hash.get(identity_hash)
            if tag is None:
                tag, _created = PartTag.objects.using(database).get_or_create(
                    identity_hash=identity_hash,
                    defaults={"name": name},
                )
                if normalized_name(tag.name).casefold() != identity:
                    raise RuntimeError(
                        "SHA-256 collision while migrating part tags; migration aborted."
                    )
                tags_by_hash[identity_hash] = tag
            assignments.append(
                through(part_id=part.pk, parttag_id=tag.pk)
            )

    through.objects.using(database).bulk_create(assignments, ignore_conflicts=True)


def restore_legacy_state(apps, schema_editor):
    Part = apps.get_model("plm", "Part")
    PartTag = apps.get_model("plm", "PartTag")
    database = schema_editor.connection.alias
    Part.structured_tags.through.objects.using(database).all().delete()
    PartTag.objects.using(database).all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("plm", "0036_add_structured_part_tags"),
    ]

    operations = [
        migrations.RunPython(migrate_part_tags, restore_legacy_state),
    ]
