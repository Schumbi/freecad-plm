# Generated manually for print-project plate previews.
from django.db import migrations, models
import django.db.models.deletion
import plm.models


class Migration(migrations.Migration):
    dependencies = [("plm", "0021_print_projects")]

    operations = [
        migrations.CreateModel(
            name="PrintProjectPlate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("plate_number", models.PositiveIntegerField()),
                ("name", models.CharField(max_length=255)),
                ("preview", models.FileField(blank=True, max_length=500, upload_to=plm.models.print_project_plate_preview_upload_path)),
                ("print_project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="plates", to="plm.printproject")),
            ],
            options={"ordering": ["plate_number"]},
        ),
        migrations.AddConstraint(
            model_name="printprojectplate",
            constraint=models.UniqueConstraint(fields=("print_project", "plate_number"), name="unique_print_project_plate_number"),
        ),
    ]
