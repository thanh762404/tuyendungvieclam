from django.db import migrations, models


def populate_package_start_dates(apps, schema_editor):
    database = schema_editor.connection.alias
    RecruiterAccount = apps.get_model("jobs", "RecruiterAccount")
    PackageTransaction = apps.get_model("jobs", "PackageTransaction")

    for account in RecruiterAccount.objects.using(database).exclude(
        active_package_id=None
    ).iterator(chunk_size=500):
        transactions = PackageTransaction.objects.using(database).filter(
            recruiter_id=account.user_id,
            package_id=account.active_package_id,
            status="approved",
        )
        latest_transaction = max(
            transactions,
            key=lambda item: item.verified_at or item.created_at,
            default=None,
        )
        if latest_transaction:
            account.package_started_at = (
                latest_transaction.verified_at or latest_transaction.created_at
            )
            account.save(update_fields=("package_started_at",))


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("jobs", "0035_qualifiedcandidate_vietnamese_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="recruiteraccount",
            name="package_started_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Ngày bắt đầu gói cước",
            ),
        ),
        migrations.RunPython(populate_package_start_dates, migrations.RunPython.noop),
    ]
