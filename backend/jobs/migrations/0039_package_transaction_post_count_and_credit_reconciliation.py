from django.db import migrations, models
from django.db.models import Sum


def snapshot_package_post_counts_and_reconcile_credits(apps, schema_editor):
    database = schema_editor.connection.alias
    PackageTransaction = apps.get_model("jobs", "PackageTransaction")
    RecruiterAccount = apps.get_model("jobs", "RecruiterAccount")

    transactions = PackageTransaction.objects.using(database).select_related(
        "package"
    )
    batch = []
    for purchase in transactions.iterator(chunk_size=500):
        purchase.package_posts_count = purchase.package.post_limit
        batch.append(purchase)
        if len(batch) == 500:
            PackageTransaction.objects.using(database).bulk_update(
                batch, ("package_posts_count",)
            )
            batch.clear()
    if batch:
        PackageTransaction.objects.using(database).bulk_update(
            batch, ("package_posts_count",)
        )

    purchased_totals = (
        PackageTransaction.objects.using(database)
        .filter(status="approved")
        .values("recruiter_id")
        .annotate(total=Sum("package_posts_count"))
    )
    for row in purchased_totals.iterator(chunk_size=500):
        account = RecruiterAccount.objects.using(database).filter(
            user_id=row["recruiter_id"]
        ).first()
        if account is None:
            continue
        account.total_posts_purchased = row["total"] or 0
        if account.total_posts_purchased and (
            account.posts_remaining > account.total_posts_purchased
        ):
            account.posts_remaining = account.total_posts_purchased
            account.save(
                update_fields=("total_posts_purchased", "posts_remaining")
            )
        else:
            account.save(update_fields=("total_posts_purchased",))


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0038_recruiteraccount_total_posts_purchased"),
    ]

    operations = [
        migrations.AddField(
            model_name="packagetransaction",
            name="package_posts_count",
            field=models.PositiveIntegerField(
                default=0,
                verbose_name="Số tin của gói tại thời điểm mua",
            ),
        ),
        migrations.RunPython(
            snapshot_package_post_counts_and_reconcile_credits,
            migrations.RunPython.noop,
        ),
    ]
