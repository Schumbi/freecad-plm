from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("plm", "0032_projectdocument_projectdocumentversion_and_more")]

    operations = [
        migrations.AddField(
            model_name="project",
            name="main_part",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="plm.part"),
        ),
    ]
