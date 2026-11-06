from django.db import migrations, models
from django.db.models import Sum


def populate_total_posts_purchased(apps, schema_editor):
    database = schema_editor.connection.alias
    RecruiterAccount = apps.get_model("jobs", "RecruiterAccount")
    PackageTransaction = apps.get_model("jobs", "PackageTransaction")

    totals = (
        PackageTransaction.objects.using(database)
        .filter(status="approved")
        .values("recruiter_id")
        .annotate(total=Sum("package__post_limit"))
    )
    for row in totals.iterator(chunk_size=500):
        account, _ = RecruiterAccount.objects.using(database).get_or_create(
            user_id=row["recruiter_id"]
        )
        account.total_posts_purchased = row["total"] or 0
        account.save(update_fields=("total_posts_purchased",))


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0037_job_recruiter_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="recruiteraccount",
            name="total_posts_purchased",
            field=models.PositiveIntegerField(
                default=0,
                verbose_name="Tổng số lượt đăng đã mua",
            ),
        ),
        migrations.RunPython(
            populate_total_posts_purchased,
            migrations.RunPython.noop,
        ),
    ]
