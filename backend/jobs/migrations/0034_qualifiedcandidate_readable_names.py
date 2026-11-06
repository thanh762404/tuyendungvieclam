from django.core.exceptions import ObjectDoesNotExist
from django.db import migrations, models


def populate_readable_names(apps, schema_editor):
    database = schema_editor.connection.alias
    QualifiedCandidate = apps.get_model("jobs", "QualifiedCandidate")

    batch = []
    entries = QualifiedCandidate.objects.using(database).select_related(
        "application__candidate",
        "application__job__recruiter",
        "application__job",
    )
    for entry in entries.iterator(chunk_size=500):
        candidate = entry.application.candidate
        recruiter = entry.application.job.recruiter
        job = entry.application.job

        candidate_name = " ".join(
            part for part in (candidate.first_name, candidate.last_name) if part
        ).strip()
        if not candidate_name:
            try:
                candidate_name = candidate.profile.candidate_name
            except ObjectDoesNotExist:
                candidate_name = ""
        candidate_name = candidate_name or candidate.username or candidate.email

        company_name = ""
        try:
            company_name = recruiter.company_profile.company_name.strip()
        except ObjectDoesNotExist:
            pass
        if company_name == recruiter.email:
            company_name = ""

        entry.candidate_name = candidate_name or "Ứng viên"
        entry.recruiter_name = company_name or "Nhà tuyển dụng"
        entry.company_name = (
            company_name or job.company_name or "Chưa cập nhật"
        )
        entry.job_title = job.title
        batch.append(entry)
        if len(batch) == 500:
            QualifiedCandidate.objects.using(database).bulk_update(
                batch,
                (
                    "candidate_name",
                    "recruiter_name",
                    "company_name",
                    "job_title",
                ),
            )
            batch.clear()

    if batch:
        QualifiedCandidate.objects.using(database).bulk_update(
            batch,
            ("candidate_name", "recruiter_name", "company_name", "job_title"),
        )


def drop_readable_view(apps, schema_editor):
    schema_editor.execute("DROP VIEW IF EXISTS jobs_qualifiedcandidate_readable")


def create_readable_view(apps, schema_editor):
    schema_editor.execute(
        """
        CREATE VIEW jobs_qualifiedcandidate_readable AS
        SELECT
            qualified.candidate_name,
            qualified.recruiter_name,
            qualified.company_name,
            qualified.job_title,
            qualified.status,
            qualified.qualified_at,
            application.applied_at
        FROM jobs_qualifiedcandidate AS qualified
        JOIN jobs_application AS application
            ON application.id = qualified.application_id
        """
    )


def restore_legacy_readable_view(apps, schema_editor):
    if schema_editor.connection.vendor == "sqlite":
        candidate_name = """
            COALESCE(
                NULLIF(
                    TRIM(
                        COALESCE(candidate.first_name, '') || ' ' ||
                        COALESCE(candidate.last_name, '')
                    ),
                    ''
                ),
                NULLIF(profile.candidate_name, ''),
                NULLIF(candidate.username, ''),
                candidate.email
            )
        """
    else:
        candidate_name = """
            COALESCE(
                NULLIF(
                    TRIM(
                        CONCAT_WS(
                            ' ',
                            NULLIF(candidate.first_name, ''),
                            NULLIF(candidate.last_name, '')
                        )
                    ),
                    ''
                ),
                NULLIF(profile.candidate_name, ''),
                NULLIF(candidate.username, ''),
                candidate.email
            )
        """

    schema_editor.execute(
        f"""
        CREATE VIEW jobs_qualifiedcandidate_readable AS
        SELECT
            {candidate_name} AS candidate_name,
            COALESCE(
                NULLIF(NULLIF(company.company_name, recruiter.email), ''),
                'Nhà tuyển dụng'
            ) AS recruiter_name,
            COALESCE(
                NULLIF(company.company_name, ''),
                NULLIF(job.company_name, ''),
                'Chưa cập nhật'
            ) AS company_name,
            job.title AS job_title,
            qualified.status,
            qualified.qualified_at,
            application.applied_at
        FROM jobs_qualifiedcandidate AS qualified
        JOIN accounts_user AS candidate
            ON candidate.id = qualified.candidate_id
        LEFT JOIN accounts_profile AS profile
            ON profile.user_id = candidate.id
        JOIN accounts_user AS recruiter
            ON recruiter.id = qualified.recruiter_id
        LEFT JOIN jobs_companyprofile AS company
            ON company.user_id = recruiter.id
        JOIN jobs_job AS job
            ON job.id = qualified.job_id
        JOIN jobs_application AS application
            ON application.id = qualified.application_id
        """
    )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("jobs", "0033_qualifiedcandidate_readable_view"),
    ]

    operations = [
        migrations.RunPython(drop_readable_view, restore_legacy_readable_view),
        migrations.AddField(
            model_name="qualifiedcandidate",
            name="candidate_name",
            field=models.CharField(
                blank=True,
                max_length=255,
                verbose_name="Tên ứng viên",
            ),
        ),
        migrations.AddField(
            model_name="qualifiedcandidate",
            name="recruiter_name",
            field=models.CharField(
                blank=True,
                max_length=255,
                verbose_name="Tên nhà tuyển dụng",
            ),
        ),
        migrations.AddField(
            model_name="qualifiedcandidate",
            name="company_name",
            field=models.CharField(
                blank=True,
                max_length=255,
                verbose_name="Tên công ty",
            ),
        ),
        migrations.AddField(
            model_name="qualifiedcandidate",
            name="job_title",
            field=models.CharField(
                blank=True,
                max_length=255,
                verbose_name="Tên công việc",
            ),
        ),
        migrations.RunPython(populate_readable_names, migrations.RunPython.noop),
        migrations.RunPython(create_readable_view, drop_readable_view),
    ]
