from django.db import migrations, models


def drop_job_views(apps, schema_editor):
    schema_editor.execute("DROP VIEW IF EXISTS jobs_job_expiration_counts")
    schema_editor.execute("DROP VIEW IF EXISTS jobs_job_expiration_status")


def create_job_views(apps, schema_editor):
    schema_editor.execute(
        """
        CREATE VIEW jobs_job_expiration_status AS
        SELECT
            job.title AS job_title,
            COALESCE(
                NULLIF(company.company_name, ''),
                NULLIF(job.company_name, ''),
                'Chưa cập nhật'
            ) AS company_name,
            COALESCE(
                NULLIF(NULLIF(company.company_name, recruiter.email), ''),
                'Nhà tuyển dụng'
            ) AS recruiter_name,
            job.location,
            job.salary,
            job.expires_at,
            CASE
                WHEN job.expires_at IS NULL
                    OR job.expires_at >= CURRENT_TIMESTAMP
                THEN 'Còn hạn'
                ELSE 'Hết hạn'
            END AS expiration_status
        FROM jobs_job AS job
        JOIN accounts_user AS recruiter
            ON recruiter.id = job.recruiter_id
        LEFT JOIN jobs_companyprofile AS company
            ON company.user_id = recruiter.id
        """
    )
    schema_editor.execute(
        """
        CREATE VIEW jobs_job_expiration_counts AS
        SELECT
            COUNT(*) AS total_jobs,
            COALESCE(SUM(
                CASE
                    WHEN expires_at IS NULL
                        OR expires_at >= CURRENT_TIMESTAMP
                    THEN 1 ELSE 0
                END
            ), 0) AS active_jobs,
            COALESCE(SUM(
                CASE
                    WHEN expires_at < CURRENT_TIMESTAMP
                    THEN 1 ELSE 0
                END
            ), 0) AS expired_jobs
        FROM jobs_job
        """
    )


def populate_job_recruiter_names(apps, schema_editor):
    database = schema_editor.connection.alias
    Job = apps.get_model("jobs", "Job")
    CompanyProfile = apps.get_model("jobs", "CompanyProfile")
    User = apps.get_model("accounts", "User")

    company_names = dict(
        CompanyProfile.objects.using(database).values_list("user_id", "company_name")
    )
    users = User.objects.using(database).in_bulk()
    batch = []

    for job in Job.objects.using(database).iterator(chunk_size=500):
        recruiter = users.get(job.recruiter_id)
        company_name = (company_names.get(job.recruiter_id) or "").strip()
        if not company_name:
            company_name = (job.company_name or "").strip()
        if not company_name and recruiter:
            company_name = (
                " ".join(
                    part
                    for part in (recruiter.first_name, recruiter.last_name)
                    if part
                ).strip()
                or recruiter.username
                or recruiter.email
            )

        job.recruiter_name = company_name
        if not job.company_name:
            job.company_name = company_name
        batch.append(job)

        if len(batch) == 500:
            Job.objects.using(database).bulk_update(
                batch, ("recruiter_name", "company_name")
            )
            batch.clear()

    if batch:
        Job.objects.using(database).bulk_update(
            batch, ("recruiter_name", "company_name")
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("jobs", "0036_recruiteraccount_package_started_at"),
        ("accounts", "0008_remove_profile_cv_skills"),
    ]

    operations = [
        migrations.RunPython(drop_job_views, create_job_views),
        migrations.AddField(
            model_name="job",
            name="recruiter_name",
            field=models.CharField(
                blank=True,
                max_length=255,
                verbose_name="Tên công ty nhà tuyển dụng",
            ),
        ),
        migrations.RunPython(populate_job_recruiter_names, migrations.RunPython.noop),
        migrations.RunPython(create_job_views, drop_job_views),
    ]
