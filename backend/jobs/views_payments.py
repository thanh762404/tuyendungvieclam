import hmac
import json
import logging
import re
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import PackageTransaction
from .payment_services import activate_package_transaction


logger = logging.getLogger(__name__)


def _sepay_api_key_is_valid(request):
    secret = getattr(settings, "SEPAY_WEBHOOK_SECRET", "")
    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if not secret or not separator or scheme.casefold() != "apikey":
        return False
    return hmac.compare_digest(secret, token.strip())


@csrf_exempt
@require_POST
def sepay_webhook(request):
    if not getattr(settings, "SEPAY_WEBHOOK_SECRET", ""):
        logger.error("SEPAY_WEBHOOK_SECRET chưa được cấu hình.")
        return JsonResponse({"success": False}, status=503)
    if not _sepay_api_key_is_valid(request):
        return JsonResponse({"success": False, "error": "Invalid credentials"}, status=401)

    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"success": False, "error": "Invalid event"}, status=400)

    event_id = payload.get("id")
    if event_id is None:
        return JsonResponse({"success": False, "error": "Missing event id"}, status=400)
    if str(payload.get("transferType", "")).casefold() != "in":
        return JsonResponse({"success": True})

    configured_account = str(getattr(settings, "SEPAY_BANK_ACCOUNT", "")).strip()
    received_account = str(payload.get("accountNumber", "")).strip()
    if not configured_account or received_account != configured_account:
        logger.warning("Bỏ qua giao dịch SePay gửi đến tài khoản không khớp.")
        return JsonResponse({"success": True})

    try:
        received_amount = Decimal(str(payload.get("transferAmount")))
    except (InvalidOperation, TypeError):
        return JsonResponse({"success": False, "error": "Invalid amount"}, status=400)
    if not received_amount.is_finite() or received_amount <= 0:
        return JsonResponse({"success": False, "error": "Invalid amount"}, status=400)

    content = " ".join(
        str(payload.get(field) or "")
        for field in ("content", "description", "code")
    ).upper()
    payment_codes = re.findall(
        r"(?<![A-Z0-9])CTJ[A-Z0-9]{12}(?![A-Z0-9])",
        content,
    )
    if not payment_codes:
        return JsonResponse({"success": True})

    with transaction.atomic():
        if PackageTransaction.objects.filter(
            sepay_transaction_id=str(event_id)
        ).exists():
            return JsonResponse({"success": True})

        matching_order = (
            PackageTransaction.objects.select_for_update()
            .filter(status="pending", payment_code__in=payment_codes)
            .first()
        )
        if matching_order is None:
            return JsonResponse({"success": True})
        if received_amount != matching_order.amount:
            matching_order.sepay_received_amount = received_amount
            matching_order.save(update_fields=["sepay_received_amount"])
            logger.warning(
                "SePay event %s không khớp số tiền của giao dịch #%s.",
                event_id,
                matching_order.pk,
            )
            return JsonResponse({"success": True})

        activated = activate_package_transaction(
            matching_order.pk,
            sepay_transaction_id=str(event_id),
            sepay_received_amount=received_amount,
        )
        if not activated:
            logger.warning("Không thể kích hoạt gói từ SePay event %s.", event_id)
    return JsonResponse({"success": True})
