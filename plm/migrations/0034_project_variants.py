from django.db import migrations, models
import django.db.models.deletion


def configure_rodeln(apps, schema_editor):
    Project = apps.get_model("plm", "Project")
    Part = apps.get_model("plm", "Part")
    PartFamily = apps.get_model("plm", "PartFamily")
    ProjectVariant = apps.get_model("plm", "ProjectVariant")
    project = Project.objects.filter(code="RODELN").first()
    if project is None:
        return
    parts = {part.number: part for part in Part.objects.filter(project=project)}
    groups = {
        "Normal": (0, ("A-001", "A-002", "P-001", "P-002", "P-003")),
        "12 Chips": (1, ("P-004", "P-005", "P-006", "P-007", "P-008")),
        "20 Chips": (2, ("P-009", "P-010", "P-011", "P-012", "P-013")),
    }
    if not all(number in parts for _, numbers in groups.values() for number in numbers):
        return
    families = {family.name: family for family in PartFamily.objects.filter(project=project)}
    if "Zusammenbau" not in families or "Druck" not in families:
        return
    for name, (position, numbers) in groups.items():
        variant, _ = ProjectVariant.objects.get_or_create(project=project, name=name, defaults={"position": position})
        Part.objects.filter(pk__in=[parts[number].pk for number in numbers], project_variant__isnull=True).update(project_variant=variant)
    project.variant_assembly_family = families["Zusammenbau"]
    project.variant_print_family = families["Druck"]
    project.save(update_fields=["variant_assembly_family", "variant_print_family"])


class Migration(migrations.Migration):
    dependencies = [("plm", "0033_project_main_part")]

    operations = [
        migrations.CreateModel(
            name="ProjectVariant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=200)),
                ("position", models.PositiveIntegerField(default=0)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="variants", to="plm.project")),
            ],
            options={"ordering": ["position", "pk"], "constraints": [models.UniqueConstraint(fields=("project", "name"), name="unique_project_variant_name")]},
        ),
        migrations.AddField(model_name="part", name="project_variant", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="parts", to="plm.projectvariant")),
        migrations.AddField(model_name="project", name="variant_assembly_family", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="plm.partfamily")),
        migrations.AddField(model_name="project", name="variant_print_family", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="plm.partfamily")),
        migrations.RunPython(configure_rodeln, migrations.RunPython.noop),
    ]
