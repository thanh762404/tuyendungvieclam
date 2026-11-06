from django.db import migrations, models


STATUS_TRANSLATIONS = {
    "InterviewPassed": "Đạt phỏng vấn",
    "Trial": "Đang thử việc",
    "Hired": "Đã nhận / Đang đi làm",
}


def translate_qualified_statuses(apps, schema_editor):
    database = schema_editor.connection.alias
    QualifiedCandidate = apps.get_model("jobs", "QualifiedCandidate")

    for code, label in STATUS_TRANSLATIONS.items():
        QualifiedCandidate.objects.using(database).filter(status=code).update(
            status=label
        )


def restore_qualified_status_codes(apps, schema_editor):
    database = schema_editor.connection.alias
    QualifiedCandidate = apps.get_model("jobs", "QualifiedCandidate")

    for code, label in STATUS_TRANSLATIONS.items():
        QualifiedCandidate.objects.using(database).filter(status=label).update(
            status=code
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("jobs", "0034_qualifiedcandidate_readable_names"),
    ]

    operations = [
        migrations.RunPython(
            translate_qualified_statuses,
            restore_qualified_status_codes,
        ),
        migrations.AlterField(
            model_name="qualifiedcandidate",
            name="status",
            field=models.CharField(
                choices=[
                    ("Đạt phỏng vấn", "Đạt phỏng vấn"),
                    ("Đang thử việc", "Đang thử việc"),
                    ("Đã nhận / Đang đi làm", "Đã nhận / Đang đi làm"),
                ],
                max_length=50,
                verbose_name="Trạng thái đạt",
            ),
        ),
    ]
