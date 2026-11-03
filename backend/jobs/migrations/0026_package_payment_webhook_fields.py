import uuid

from django.db import migrations, models

import jobs.models


def populate_payment_codes(apps, schema_editor):
    PackageTransaction = apps.get_model("jobs", "PackageTransaction")
    for purchase in PackageTransaction.objects.filter(payment_code__isnull=True):
        purchase.payment_code = f"CTJ{uuid.uuid4().hex[:12].upper()}"
        purchase.save(update_fields=["payment_code"])


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0025_notification"),
    ]

    operations = [
        migrations.AddField(
            model_name="packagetransaction",
            name="payment_code",
            field=models.CharField(
                blank=True,
                max_length=15,
                null=True,
                verbose_name="Mã nội dung thanh toán",
            ),
        ),
        migrations.AddField(
            model_name="packagetransaction",
            name="sepay_transaction_id",
            field=models.CharField(
                blank=True,
                max_length=100,
                null=True,
                verbose_name="Mã giao dịch SePay",
            ),
        ),
        migrations.AddField(
            model_name="packagetransaction",
            name="verified_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Thời gian xác nhận thanh toán",
            ),
        ),
        migrations.RunPython(populate_payment_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="packagetransaction",
            name="payment_code",
            field=models.CharField(
                default=jobs.models.generate_package_payment_code,
                max_length=15,
                unique=True,
                verbose_name="Mã nội dung thanh toán",
            ),
        ),
        migrations.AlterField(
            model_name="packagetransaction",
            name="sepay_transaction_id",
            field=models.CharField(
                blank=True,
                max_length=100,
                null=True,
                unique=True,
                verbose_name="Mã giao dịch SePay",
            ),
        ),
    ]
