import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def populate_qualified_candidate_ownership(apps, schema_editor):
    database = schema_editor.connection.alias
    QualifiedCandidate = apps.get_model("jobs", "QualifiedCandidate")

    batch = []
    for entry in QualifiedCandidate.objects.using(database).select_related(
        "application__job",
        "application__candidate",
    ).iterator(chunk_size=500):
        entry.candidate_id = entry.application.candidate_id
        entry.job_id = entry.application.job_id
        entry.recruiter_id = entry.application.job.recruiter_id
        batch.append(entry)
        if len(batch) == 500:
            QualifiedCandidate.objects.using(database).bulk_update(
                batch,
                ("candidate", "job", "recruiter"),
            )
            batch.clear()

    if batch:
        QualifiedCandidate.objects.using(database).bulk_update(
            batch,
            ("candidate", "job", "recruiter"),
        )


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0031_qualifiedcandidate"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="qualifiedcandidate",
            name="candidate",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="qualified_applications",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Ứng viên",
            ),
        ),
        migrations.AddField(
            model_name="qualifiedcandidate",
            name="job",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="qualified_candidates",
                to="jobs.job",
                verbose_name="Tin tuyển dụng",
            ),
        ),
        migrations.AddField(
            model_name="qualifiedcandidate",
            name="recruiter",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="qualified_candidates",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Nhà tuyển dụng",
            ),
        ),
        migrations.RunPython(
            populate_qualified_candidate_ownership,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="qualifiedcandidate",
            name="candidate",
            field=models.ForeignKey(
                limit_choices_to={"is_candidate": True},
                on_delete=django.db.models.deletion.CASCADE,
                related_name="qualified_applications",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Ứng viên",
            ),
        ),
        migrations.AlterField(
            model_name="qualifiedcandidate",
            name="job",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="qualified_candidates",
                to="jobs.job",
                verbose_name="Tin tuyển dụng",
            ),
        ),
        migrations.AlterField(
            model_name="qualifiedcandidate",
            name="recruiter",
            field=models.ForeignKey(
                limit_choices_to={"is_recruiter": True},
                on_delete=django.db.models.deletion.CASCADE,
                related_name="qualified_candidates",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Nhà tuyển dụng",
            ),
        ),
    ]
