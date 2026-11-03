from django.db import migrations, models


def publish_pending_jobs(apps, schema_editor):
    Job = apps.get_model("jobs", "Job")
    Job.objects.filter(status="Pending").update(status="Approved")


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0027_packagetransaction_sepay_received_amount"),
    ]

    operations = [
        migrations.AlterField(
            model_name="job",
            name="status",
            field=models.CharField(
                choices=[
                    ("Pending", "Chờ duyệt"),
                    ("Approved", "Đã duyệt"),
                    ("Rejected", "Từ chối"),
                ],
                default="Approved",
                max_length=20,
                verbose_name="Trạng thái duyệt",
            ),
        ),
        migrations.RunPython(publish_pending_jobs, migrations.RunPython.noop),
    ]
