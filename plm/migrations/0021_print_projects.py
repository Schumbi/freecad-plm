# Generated manually for the print-project workflow.
import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import plm.models


class Migration(migrations.Migration):
    dependencies = [("plm", "0020_alter_auditevent_action")]

    operations = [
        migrations.CreateModel(
            name="PrintProject",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("code", models.CharField(max_length=40)),
                ("name", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                ("storage_key", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("slicer_file", models.FileField(blank=True, max_length=500, upload_to=plm.models.print_project_upload_path)),
                ("slicer_original_filename", models.CharField(blank=True, max_length=255)),
                ("slicer_sha256", models.CharField(blank=True, max_length=64)),
                ("slicer_size_bytes", models.PositiveBigIntegerField(default=0)),
                ("slicer_metadata", models.JSONField(blank=True, default=dict)),
                ("primary_revision", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="primary_print_projects", to="plm.revision")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="print_projects", to="plm.project")),
                ("slicer_updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="updated_print_projects", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["project__code", "code"]},
        ),
        migrations.CreateModel(
            name="PrintProjectSource",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("source_type", models.CharField(choices=[("revision", "PLM-Revision"), ("external_stl", "Externe STL")], max_length=20)),
                ("storage_key", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("file", models.FileField(blank=True, max_length=500, upload_to=plm.models.print_project_source_upload_path)),
                ("original_filename", models.CharField(blank=True, max_length=255)),
                ("sha256", models.CharField(blank=True, max_length=64)),
                ("size_bytes", models.PositiveBigIntegerField(default=0)),
                ("label", models.CharField(blank=True, max_length=160)),
                ("print_project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sources", to="plm.printproject")),
                ("revision", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="plm.revision")),
                ("uploaded_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="PrintProjectSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("storage_key", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("file", models.FileField(max_length=500, upload_to=plm.models.print_project_snapshot_upload_path)),
                ("original_filename", models.CharField(max_length=255)),
                ("sha256", models.CharField(max_length=64)),
                ("size_bytes", models.PositiveBigIntegerField()),
                ("bambuddy_archive_id", models.PositiveIntegerField(blank=True, null=True, unique=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("print_project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="snapshots", to="plm.printproject")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(model_name="printproject", constraint=models.UniqueConstraint(fields=("project", "code"), name="unique_print_project_code")),
        migrations.AddConstraint(model_name="printprojectsource", constraint=models.UniqueConstraint(condition=models.Q(("source_type", "revision")), fields=("print_project", "revision"), name="unique_print_project_revision_source")),
    ]
