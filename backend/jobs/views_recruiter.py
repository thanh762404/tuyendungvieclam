from datetime import datetime, timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce, TruncMonth
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import CompanyProfileForm, JobForm
from .models import (
    Application,
    CompanyProfile,
    Job,
    JobChatMessage,
    HIRING_CAPACITY_STATUSES,
    HIRING_PIPELINE_STATUSES,
    PackageTransaction,
    QualifiedCandidate,
    RecruiterAccount,
    SubscriptionPackage,
)
from .models import PackageTransaction, RecruiterAccount

def approve_package_transaction(transaction):
    # 1. Đổi trạng thái giao dịch thành approved
    transaction.status = "approved"
    transaction.verified_at = timezone.now()
    transaction.save()

    # 2. Lấy hoặc tạo RecruiterAccount của nhà tuyển dụng tương ứng
    recruiter_account, created = RecruiterAccount.objects.get_or_create(
        user=transaction.recruiter
    )

    # 3. Lấy số lượng tin từ gói cước được mua
    package = transaction.package
    posts_to_add = transaction.package_posts_count or package.post_limit

    # 4. Cập nhật gói cước đang áp dụng và cộng dồn số tin
    recruiter_account.active_package = package
    recruiter_account.package_started_at = timezone.now()
    
    # Cộng dồn số tin vào kho và tổng số tin đã mua
    recruiter_account.posts_remaining += posts_to_add
    recruiter_account.total_posts_purchased += posts_to_add
    
    # Lưu lại trước để cập nhật posts_remaining vào CSDL
    recruiter_account.save()
    
    # 👉 5. GỌI HÀM TÍNH TOÁN LẠI ĐỂ TỰ ĐỘNG CẬP NHẬT NGÀY HẾT HẠN XA NHẤT VÀ SỐ TIN KHẢ DỤNG
    recruiter_account.update_usable_posts()

def _package_spending_context(user, selected_month=""):
    approved_transactions = PackageTransaction.objects.filter(
        recruiter=user,
        status="approved",
    )
    monthly_spending = list(
        approved_transactions.annotate(
            payment_month=TruncMonth(Coalesce("verified_at", "created_at"))
        )
        .values("payment_month")
        .annotate(total_amount=Sum("amount"), transaction_count=Count("pk"))
        .order_by("-payment_month")
    )
    selected_month_spending = next(
        (
            month
            for month in monthly_spending
            if month["payment_month"].strftime("%Y-%m") == selected_month
        ),
        None,
    )
    return {
        "package_spending_by_month": monthly_spending,
        "selected_spending_month": (
            selected_month if selected_month_spending else ""
        ),
        "selected_month_spending": selected_month_spending,
        "package_spending": approved_transactions.aggregate(
            total_amount=Sum("amount"),
            transaction_count=Count("pk"),
        ),
    }


@login_required
def recruiter_profile_view(request):
    """View cho phép nhà tuyển dụng cập nhật thông tin công ty và logo riêng"""
    if not getattr(request.user, "is_recruiter", False):
        return redirect("home")

    profile, created = CompanyProfile.objects.get_or_create(
        user=request.user,
        defaults={"company_name": "Nhà tuyển dụng"},
    )
    if request.method == "POST":
        form = CompanyProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Cập nhật thông tin công ty thành công!")
            return redirect("recruiter_profile")
    else:
        form = CompanyProfileForm(instance=profile)

    return render(
        request,
        "jobs/recruiter_profile.html",
        {
            "form": form,
            "profile": profile,
            **_package_spending_context(request.user),
        },
    )


@login_required
def recruiter_job_list(request):
    jobs = Job.objects.filter(recruiter=request.user).annotate(
        hired_count=Count(
            "applications",
            filter=Q(applications__status__in=HIRING_CAPACITY_STATUSES),
            distinct=True,
        )
    ).order_by("-created_at")
    employer_jobs = Job.objects.filter(recruiter=request.user)
    chat_messages = JobChatMessage.objects.filter(
        job__in=employer_jobs,
        is_application_update=False,
    )

    total_unread = chat_messages.filter(
        receiver=request.user,
        sender__is_candidate=True,
        is_read=False,
        is_application_update=False,
    ).count()

    conversations_dict = {}
    for msg in chat_messages.order_by("created_at", "pk"):
        candidate = msg.sender if msg.sender != request.user else msg.receiver
        if candidate == request.user:
            continue

        key = (msg.job_id, candidate.id)
        unread_for_this_candidate = chat_messages.filter(
            job_id=msg.job_id,
            sender=candidate,
            receiver=request.user,
            is_read=False,
            is_application_update=False,
        ).count()

        conversations_dict[key] = {
            "job_id": msg.job_id,
            "candidate": candidate,
            "last_message": msg.message,
            "last_time": msg.created_at,
            "unread_count": unread_for_this_candidate,
        }

    chat_conversations = sorted(
        conversations_dict.values(),
        key=lambda conversation: conversation["last_time"],
        reverse=True,
    )

    return render(
        request,
        "jobs/recruiter_job_list.html",
        {
            "jobs": jobs,
            "chat_conversations": chat_conversations,
            "total_unread": total_unread,
        },
    )


@login_required
def mark_job_chat_read(request, pk):
    if request.method != "POST":
        return JsonResponse({"status": "error"}, status=400)

    job = get_object_or_404(Job, pk=pk)
    if request.user == job.recruiter:
        candidate_id = request.POST.get("candidate_id")
        if not candidate_id:
            return JsonResponse({"status": "error"}, status=400)
        messages_qs = JobChatMessage.objects.filter(
            job=job,
            sender_id=candidate_id,
            receiver=request.user,
            is_read=False,
        )
    else:
        messages_qs = JobChatMessage.objects.filter(
            job=job,
            sender=job.recruiter,
            receiver=request.user,
            is_read=False,
        )

    messages_qs.update(is_read=True)
    return JsonResponse({"status": "success"})


def _save_new_job_with_credit(job, recruiter):
    with transaction.atomic():
        profile_account = RecruiterAccount.objects.select_for_update().get(
            user=recruiter
        )
        if profile_account.is_package_active:
            profile_account.posts_remaining -= 1
            remaining_credits = profile_account.posts_remaining
            credit_field = "posts_remaining"
            credit_source = "package"
        elif profile_account.free_posts_left > 0:
            profile_account.free_posts_left -= 1
            remaining_credits = profile_account.free_posts_left
            credit_field = "free_posts_left"
            credit_source = "free"
        else:
            return None

        job.recruiter = recruiter
        job.status = "Approved"
        job.save()
        profile_account.save(update_fields=[credit_field])

    return credit_source, remaining_credits


@login_required
def job_create(request):
    """Đăng tin mới: Ưu tiên trừ tin trong gói, nếu hết gói thì trừ tin miễn phí"""
    if not getattr(request.user, "is_recruiter", False):
        return redirect("home")

    profile_account, _ = RecruiterAccount.objects.get_or_create(user=request.user)

    now = timezone.now()
    posts_remaining = getattr(profile_account, "posts_remaining", 0)

    is_package_valid = (
        profile_account.is_package_active
        and profile_account.package_expires_at
        and profile_account.package_expires_at > now
    )

    has_free_post = profile_account.free_posts_left > 0

    if not is_package_valid and not has_free_post:
        messages.warning(
            request,
            "Bạn đã dùng hết lượt đăng tin miễn phí và gói cước hiện tại đã hết hạn"
            " hoặc chưa được kích hoạt. Vui lòng mua gói cước để tiếp tục đăng tin tuyển dụng!",
        )
        return redirect("buy_package")

    if request.method == "POST":
        form = JobForm(request.POST)
        if form.is_valid():
            job = form.save(commit=False)
            credit = _save_new_job_with_credit(job, request.user)
            if credit is None:
                messages.warning(
                    request,
                    "Bạn đã hết lượt đăng tin. Vui lòng mua gói cước để tiếp tục.",
                )
                return redirect("buy_package")
            credit_source, remaining_credits = credit
            if credit_source == "package":
                messages.success(
                    request,
                    f"Đăng tin thành công bằng gói cước! Bạn còn lại "
                    f"{remaining_credits} lượt đăng trong gói.",
                )
            else:
                messages.success(
                    request,
                    f"Đăng tin thành công bằng lượt tin miễn phí! Bạn còn lại "
                    f"{remaining_credits} lượt miễn phí.",
                )

            return redirect("recruiter_job_list")
    else:
        form = JobForm()

    return render(
        request,
        "jobs/job_form.html",
        {
            "form": form,
            "has_free_post": has_free_post,
            "has_active_package": is_package_valid,
            "profile_account": profile_account,
        },
    )


@login_required
def job_clone(request, pk):
    """Nhân bản tin tuyển dụng cũ"""
    if not getattr(request.user, "is_recruiter", False):
        return redirect("home")

    source_job = get_object_or_404(Job, pk=pk, recruiter=request.user)
    profile_account, _ = RecruiterAccount.objects.get_or_create(user=request.user)

    has_active_package = profile_account.is_package_active
    has_free_post = profile_account.free_posts_left > 0

    if not has_active_package and not has_free_post:
        messages.warning(
            request,
            "Bạn đã hết tin miễn phí và gói cước. Vui lòng mua gói để nhân bản và đăng tin mới!",
        )
        return redirect("buy_package")

    if request.method == "POST":
        form = JobForm(request.POST)
        if form.is_valid():
            new_job = form.save(commit=False)
            new_job.pk = None
            credit = _save_new_job_with_credit(new_job, request.user)
            if credit is None:
                messages.warning(
                    request,
                    "Bạn đã hết lượt đăng tin. Vui lòng mua gói cước để tiếp tục.",
                )
                return redirect("buy_package")

            messages.success(
                request, "Tạo tin tuyển dụng mới từ tin cũ thành công!"
            )
            return redirect("recruiter_job_list")
    else:
        form = JobForm(instance=source_job)

    return render(
        request,
        "jobs/job_form.html",
        {"form": form, "job": None, "is_clone": True, "clone_source": source_job},
    )


@login_required
def buy_package_view(request):
    """Create tracked bank-transfer orders and accept optional receipts."""
    if not getattr(request.user, "is_recruiter", False):
        return redirect("home")

    packages = SubscriptionPackage.objects.all()
    
    # 1. Khởi tạo profile_account trước tiên
    profile_account, _ = RecruiterAccount.objects.get_or_create(user=request.user)

    # 2. 🔥 GỌI HÀM CẬP NHẬT TÍNH TOÁN NGAY LẬP TỨC ĐỂ LÀM SẠCH DỮ LIỆU CŨ
    profile_account.update_usable_posts()

    now = timezone.now()

    has_active_package = (
        profile_account.is_package_active
        and profile_account.package_expires_at
        and profile_account.package_expires_at > now
    )

    if has_active_package:
        remaining_credits = profile_account.posts_remaining
        
        # Lấy ngày bắt đầu của giao dịch được duyệt gần đây nhất còn hạn
        last_tx = PackageTransaction.objects.filter(
            recruiter=request.user, 
            status="approved"
        ).order_by("-created_at").first()
        
        start_date = (last_tx.verified_at or last_tx.created_at) if last_tx else None
        expires_at = profile_account.package_expires_at
    else:
        remaining_credits = 0
        start_date = None
        expires_at = None

    if request.method == "POST":
        action = request.POST.get("action", "create_payment")
        if action == "upload_proof":
            active_transaction = get_object_or_404(
                PackageTransaction,
                pk=request.POST.get("transaction_id"),
                recruiter=request.user,
            )
            proof_image = request.FILES.get("proof_image")
            if not proof_image:
                messages.error(request, "Vui lòng chọn ảnh biên lai cần tải lên.")
            elif active_transaction.status == "rejected":
                messages.error(
                    request,
                    "Không thể tải biên lai lên giao dịch đã bị từ chối.",
                )
            else:
                active_transaction.proof_image = proof_image
                active_transaction.save(update_fields=["proof_image"])
                if active_transaction.status == "approved":
                    messages.success(
                        request,
                        "Đã nhận ảnh biên lai và đính kèm vào giao dịch đã xác nhận.",
                    )
                else:
                    messages.success(
                        request,
                        "Đã nhận ảnh biên lai. Gói sẽ tự kích hoạt sau khi SePay xác nhận "
                        "tiền vào tài khoản và khớp mã thanh toán, số tiền.",
                    )
            return redirect(
                f"{reverse('buy_package')}?transaction={active_transaction.pk}"
            )

        selected_package = get_object_or_404(
            SubscriptionPackage,
            pk=request.POST.get("package_id"),
        )
        purchase = PackageTransaction.objects.create(
            recruiter=request.user,
            package=selected_package,
            amount=selected_package.price,
            status="pending",
        )
        return redirect(f"{reverse('buy_package')}?transaction={purchase.pk}")

    transaction_id = request.GET.get("transaction")
    active_transaction = None
    if transaction_id:
        active_transaction = PackageTransaction.objects.filter(
            pk=transaction_id,
            recruiter=request.user,
        ).select_related("package").first()

    context = {
        "packages": packages,
        "profile_account": profile_account,
        "has_active_package": has_active_package,
        "remaining_credits": remaining_credits,
        "start_date": start_date,
        "expires_at": expires_at,
        "active_transaction": active_transaction,
        **_package_spending_context(
            request.user,
            request.GET.get("spending_month", ""),
        ),
        "sepay_bank_account": settings.SEPAY_BANK_ACCOUNT,
        "sepay_bank_account_name": getattr(
            settings, "SEPAY_BANK_ACCOUNT_NAME", "LE CHI THANH"
        ),
    }

    return render(request, "jobs/buy_package.html", context)

@login_required
def package_transaction_status(request, pk):
    purchase = get_object_or_404(
        PackageTransaction,
        pk=pk,
        recruiter=request.user,
    )
    return JsonResponse(
        {
            "status": purchase.status,
            "verified_at": (
                purchase.verified_at.strftime("%d/%m/%Y %H:%M")
                if purchase.verified_at
                else None
            ),
        }
    )


@login_required
def job_edit(request, pk):
    job = get_object_or_404(Job, pk=pk, recruiter=request.user)

    if request.method == "POST":
        form = JobForm(request.POST, instance=job)
        if form.is_valid():
            updated_job = form.save(commit=False)
            updated_job.status = "Approved"
            updated_job.save()
            messages.success(request, "Cập nhật tin tuyển dụng thành công!")
            return redirect("recruiter_job_list")
    else:
        form = JobForm(instance=job)
    return render(request, "jobs/job_form.html", {"form": form, "job": job})


@login_required
def job_delete(request, pk):
    job = get_object_or_404(Job, pk=pk, recruiter=request.user)
    if request.method == "POST":
        job.delete()
        messages.success(request, "Xóa tin tuyển dụng thành công!")
        return redirect("recruiter_job_list")
    return render(request, "jobs/job_confirm_delete.html", {"job": job})


def job_detail(request, pk):
    job = get_object_or_404(Job, pk=pk)
    return render(request, "jobs/job_detail.html", {"job": job})


@login_required
def all_approved_candidates_view(request):
    qualified_entries = QualifiedCandidate.objects.filter(
        recruiter=request.user,
    ).select_related(
        'application__job',
        'application__candidate',
        'application__candidate__profile',
        'job__recruiter__company_profile',
    )
    approved_list = [entry.application for entry in qualified_entries]

    context = {
        'approved_list': approved_list
    }
    return render(request, 'jobs/all_approved_candidates.html', context)


@login_required
def job_achieved_candidates_view(request, pk):
    job = get_object_or_404(Job, pk=pk, recruiter=request.user)
    qualified_entries = QualifiedCandidate.objects.filter(
        recruiter=request.user,
        job=job,
    ).select_related(
        'application__job',
        'application__candidate',
        'application__candidate__profile',
        'job__recruiter__company_profile',
    )
    approved_list = [entry.application for entry in qualified_entries]

    return render(
        request,
        'jobs/all_approved_candidates.html',
        {'approved_list': approved_list, 'job': job},
    )


@login_required
def update_application_status(request, pk):
    """View cho phép nhà tuyển dụng cập nhật trạng thái đơn ứng tuyển và gửi email thông báo trực tiếp"""
    application = get_object_or_404(Application, pk=pk, job__recruiter=request.user)

    if request.method == "POST":
        new_status = request.POST.get("status")
        interview_info = request.POST.get("interview_details")

        # 1. Cập nhật thông tin vào Application (để hiển thị trực tiếp trong trang Việc làm đã ứng tuyển)
        application.status = new_status
        if interview_info is not None:
            application.interview_details = interview_info
        application.save()  # Tự động cập nhật thời gian updated_at mới nhất

        # 2. Gửi Email thông báo trực tiếp tới email đã đăng ký của ứng viên
        candidate_email = application.candidate.email
        status_vi = application.get_status_display_vi()

        subject = f"[CTJob] Cập nhật trạng thái ứng tuyển: {application.job.title}"
        message = (
            f"Xin chào {application.candidate.username},\n\n"
            f"Nhà tuyển dụng từ công ty '{application.job.company_name}' đã cập nhật tiến trình hồ sơ của bạn cho vị trí '{application.job.title}'.\n\n"
            f"- Trạng thái mới: {status_vi}\n"
        )

        if interview_info:
            message += f"- Thông tin lịch hẹn / Chi tiết: {interview_info}\n"

        message += "\nVui lòng đăng nhập vào hệ thống CTJob để xem chi tiết.\n\nTrân trọng,\nĐội ngũ CTJob."

        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "webmaster@localhost"),
                recipient_list=[candidate_email],
                fail_silently=True,
            )
        except Exception as e:
            print(f"Lỗi gửi email: {e}")

        messages.success(request, "Cập nhật trạng thái ứng tuyển và gửi thông báo qua email thành công!")
        return redirect("recruiter_job_list")

    return render(request, "jobs/update_application_status.html", {"application": application})