from datetime import datetime, timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db.models import Count, Q
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
    RecruiterAccount,
    SubscriptionPackage,
)


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
        request, "jobs/recruiter_profile.html", {"form": form, "profile": profile}
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
            job.recruiter = request.user
            job.status = "Approved"
            job.save()

            if is_package_valid and posts_remaining > 0:
                profile_account.posts_remaining -= 1
                if profile_account.posts_remaining <= 0:
                    profile_account.is_package_active = False
                profile_account.save()

                messages.success(
                    request,
                    f"Đăng tin thành công bằng gói cước! Bạn còn lại "
                    f"{profile_account.posts_remaining} lượt đăng trong gói.",
                )
            elif is_package_valid:
                messages.success(
                    request,
                    "Đăng tin thành công bằng gói cước hiện tại của bạn!",
                )
            elif has_free_post:
                profile_account.free_posts_left -= 1
                profile_account.save()
                messages.success(
                    request,
                    f"Đăng tin thành công bằng lượt tin miễn phí! Bạn còn lại "
                    f"{profile_account.free_posts_left} lượt miễn phí.",
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
            new_job.recruiter = request.user
            new_job.status = "Approved"
            new_job.save()

            if has_active_package:
                profile_account.posts_remaining -= 1
                profile_account.save()
            elif has_free_post:
                profile_account.free_posts_left -= 1
                profile_account.save()

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
    profile_account, _ = RecruiterAccount.objects.get_or_create(user=request.user)

    now = timezone.now()

    has_active_package = (
        profile_account.is_package_active
        and profile_account.package_expires_at
        and profile_account.package_expires_at > now
    )

    if has_active_package:
        remaining_credits = profile_account.posts_remaining
        
        # --- ĐOẠN SỬA LỖI Ở ĐÂY ---
        # Lấy ngày tạo giao dịch thành công mới nhất của nhà tuyển dụng làm ngày bắt đầu gói
        last_tx = PackageTransaction.objects.filter(
            recruiter=request.user, 
            status="approved"
        ).order_by("-created_at").first()
        
        start_date = last_tx.created_at if last_tx else None
        # ---------------------------
        
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
    approved_list = Application.objects.filter(
        job__recruiter=request.user,
        status__in=HIRING_PIPELINE_STATUSES,
    ).select_related('job', 'candidate')
    
    context = {
        'approved_list': approved_list
    }
    return render(request, 'jobs/all_approved_candidates.html', context)


@login_required
def job_achieved_candidates_view(request, pk):
    job = get_object_or_404(Job, pk=pk, recruiter=request.user)
    approved_list = Application.objects.filter(
        job=job,
        status__in=HIRING_PIPELINE_STATUSES,
    ).select_related('candidate')

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