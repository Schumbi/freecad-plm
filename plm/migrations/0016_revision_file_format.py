from pathlib import PurePosixPath

from django.db import migrations, models


def infer_existing_file_formats(apps, schema_editor):
    Revision = apps.get_model("plm", "Revision")
    for revision in Revision.objects.all().only("id", "original_filename"):
        suffix = PurePosixPath(revision.original_filename or "").suffix.lower()
        if suffix in {".step", ".stp"}:
            file_format = "step"
        elif suffix == ".stl":
            file_format = "stl"
        else:
            file_format = "fcstd"
        Revision.objects.filter(id=revision.id).update(file_format=file_format)


class Migration(migrations.Migration):
    dependencies = [("plm", "0015_alter_auditevent_action_checkoutfileaddition")]

    operations = [
        migrations.AddField(
            model_name="revision",
            name="file_format",
            field=models.CharField(
                choices=[("fcstd", "FreeCAD"), ("step", "STEP"), ("stl", "STL")],
                default="fcstd",
                max_length=10,
            ),
        ),
        migrations.RunPython(infer_existing_file_formats, migrations.RunPython.noop),
    ]
