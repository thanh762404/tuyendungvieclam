from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0026_package_payment_webhook_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="packagetransaction",
            name="sepay_received_amount",
            field=models.DecimalField(
                blank=True,
                decimal_places=0,
                max_digits=10,
                null=True,
                verbose_name="Số tiền nhận từ SePay",
            ),
        ),
    ]
