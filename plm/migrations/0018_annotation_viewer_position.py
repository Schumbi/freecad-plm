from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("plm", "0017_alter_auditevent_action_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="annotation",
            name="viewer_anchor",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="annotation",
            name="viewer_camera",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
