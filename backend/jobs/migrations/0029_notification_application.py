import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0028_publish_jobs_without_review"),
    ]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="application",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="notifications",
                to="jobs.application",
                verbose_name="Đơn ứng tuyển liên quan",
            ),
        ),
    ]
