from django.db import migrations


def create_readable_view(apps, schema_editor):
    if schema_editor.connection.vendor == "sqlite":
        schema_editor.execute(
            """
            CREATE VIEW IF NOT EXISTS jobs_qualifiedcandidate_readable AS
            SELECT
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
                ) AS candidate_name,
                COALESCE(
                    NULLIF(
                        NULLIF(company.company_name, recruiter.email),
                        ''
                    ),
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
        schema_editor.execute(
            """
            CREATE VIEW IF NOT EXISTS jobs_job_expiration_status AS
            SELECT
                job.title AS job_title,
                COALESCE(
                    NULLIF(company.company_name, ''),
                    NULLIF(job.company_name, ''),
                    'Chưa cập nhật'
                ) AS company_name,
                COALESCE(
                    NULLIF(
                        NULLIF(company.company_name, recruiter.email),
                        ''
                    ),
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
            CREATE VIEW IF NOT EXISTS jobs_job_expiration_counts AS
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
    elif schema_editor.connection.vendor == "mysql":
        schema_editor.execute(
            """
            CREATE OR REPLACE VIEW jobs_qualifiedcandidate_readable AS
            SELECT
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
                ) AS candidate_name,
                COALESCE(
                    NULLIF(
                        NULLIF(company.company_name, recruiter.email),
                        ''
                    ),
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
        schema_editor.execute(
            """
            CREATE OR REPLACE VIEW jobs_job_expiration_status AS
            SELECT
                job.title AS job_title,
                COALESCE(
                    NULLIF(company.company_name, ''),
                    NULLIF(job.company_name, ''),
                    'Chưa cập nhật'
                ) AS company_name,
                COALESCE(
                    NULLIF(
                        NULLIF(company.company_name, recruiter.email),
                        ''
                    ),
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
            CREATE OR REPLACE VIEW jobs_job_expiration_counts AS
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


def drop_readable_view(apps, schema_editor):
    for view_name in (
        "jobs_job_expiration_counts",
        "jobs_job_expiration_status",
        "jobs_qualifiedcandidate_readable",
    ):
        schema_editor.execute(f"DROP VIEW IF EXISTS {view_name}")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_remove_profile_cv_skills"),
        ("jobs", "0032_qualifiedcandidate_ownership"),
    ]

    operations = [
        migrations.RunPython(create_readable_view, drop_readable_view),
    ]

    atomic = False
