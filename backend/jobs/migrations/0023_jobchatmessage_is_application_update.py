from django.db import migrations, models


def mark_existing_application_updates(apps, schema_editor):
    JobChatMessage = apps.get_model("jobs", "JobChatMessage")
    JobChatMessage.objects.filter(
        message__startswith="Hồ sơ ứng tuyển vị trí '"
    ).update(is_application_update=True)


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0022_job_max_hires_application_hiring_statuses"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobchatmessage",
            name="is_application_update",
            field=models.BooleanField(default=False, verbose_name="Thông báo cập nhật hồ sơ"),
        ),
        migrations.RunPython(
            mark_existing_application_updates,
            migrations.RunPython.noop,
        ),
    ]
