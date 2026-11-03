from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import PackageTransaction, RecruiterAccount


def activate_package_transaction(
    transaction_id,
    sepay_transaction_id=None,
    sepay_received_amount=None,
):
    with transaction.atomic():
        purchase = (
            PackageTransaction.objects.select_for_update()
            .select_related("package", "recruiter")
            .get(pk=transaction_id)
        )
        if purchase.status == "approved":
            return False
        if purchase.status != "pending":
            return False
        if sepay_transaction_id:
            duplicate = PackageTransaction.objects.filter(
                sepay_transaction_id=sepay_transaction_id
            ).exclude(pk=purchase.pk).exists()
            if duplicate:
                return False
            purchase.sepay_transaction_id = str(sepay_transaction_id)
            purchase.verified_at = timezone.now()
            purchase.sepay_received_amount = sepay_received_amount
        purchase.status = "approved"
        update_fields = ["status"]
        if sepay_transaction_id:
            update_fields.extend(
                ["sepay_transaction_id", "sepay_received_amount", "verified_at"]
            )
        try:
            with transaction.atomic():
                purchase.save(update_fields=update_fields)
        except IntegrityError:
            return False

        recruiter_account, _ = RecruiterAccount.objects.get_or_create(
            user=purchase.recruiter
        )
        recruiter_account = RecruiterAccount.objects.select_for_update().get(
            pk=recruiter_account.pk
        )
        recruiter_account.active_package = purchase.package
        recruiter_account.posts_remaining += purchase.package.post_limit
        now = timezone.now()
        package_is_active = (
            recruiter_account.package_expires_at is not None
            and recruiter_account.package_expires_at > now
        )
        if package_is_active:
            recruiter_account.posts_remaining += purchase.package.post_limit
            recruiter_account.package_expires_at += timedelta(
                days=purchase.package.duration_days
            )
        else:
            recruiter_account.posts_remaining = purchase.package.post_limit
            recruiter_account.package_expires_at = now + timedelta(
                days=purchase.package.duration_days
            )
        recruiter_account.save(
            update_fields=["active_package", "posts_remaining", "package_expires_at"]
        )
        return True
