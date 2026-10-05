from datetime import timedelta
import mimetypes

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.models import User
from .models import Application, ContactMessage, Job, PackageTransaction, RecruiterAccount


@staff_member_required
def custom_admin_dashboard(request):
    """Trang chủ Admin: Thống kê tổng quan hệ thống và hiển thị tin nhắn hỗ trợ"""
    total_jobs = Job.objects.count()
    total_applications = Application.objects.count()
    total_users = User.objects.count()
    users = User.objects.all().order_by("-date_joined")
    contact_messages = ContactMessage.objects.all().order_by("-created_at")

    context = {
        "total_jobs": total_jobs,
        "total_applications": total_applications,
        "total_users": total_users,
        "users": users,
        "contact_messages": contact_messages,
    }
    return render(request, "admin/custom_dashboard.html", context)


@staff_member_required
def admin_manage_users(request):
    """Trang quản lý danh sách tài khoản có phân trang, tìm kiếm và lọc theo quyền hạn"""
    query = request.GET.get("q", "").strip()
    role_filter = request.GET.get("role", "").strip()

    role_choices = [
        ("candidate", "Ứng viên"),
        ("recruiter", "Nhà tuyển dụng"),
        ("admin", "Admin"),
    ]

    user_list = User.objects.all().order_by("-date_joined")

    if query:
        user_list = user_list.filter(
            Q(username__icontains=query) | Q(email__icontains=query)
        )

    if role_filter == "candidate":
        user_list = user_list.filter(is_candidate=True)
    elif role_filter == "recruiter":
        user_list = user_list.filter(is_recruiter=True)
    elif role_filter == "admin":
        user_list = user_list.filter(Q(is_staff=True) | Q(is_superuser=True))

    paginator = Paginator(user_list, 10)
    page_number = request.GET.get("page")
    users = paginator.get_page(page_number)

    return render(
        request,
        "admin/manage_users.html",
        {
            "users": users,
            "query": query,
            "role_filter": role_filter,
            "role_choices": role_choices,
        },
    )


@staff_member_required
def admin_delete_user(request, pk):
    """Xóa tài khoản người dùng"""
    user_to_delete = get_object_or_404(User, pk=pk)
    if user_to_delete != request.user:
        user_to_delete.delete()
    return redirect("admin_manage_users")


@staff_member_required
def admin_recruiter_cv(request, pk):
    recruiter = get_object_or_404(User, pk=pk, is_recruiter=True)
    if not recruiter.recruiter_cv:
        raise Http404

    try:
        cv_file = recruiter.recruiter_cv.open("rb")
    except OSError as error:
        raise Http404 from error

    filename = recruiter.recruiter_cv.name.rsplit("/", 1)[-1]
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return FileResponse(cv_file, as_attachment=False, filename=filename, content_type=content_type)


@staff_member_required
def admin_approve_recruiter(request, pk):
    if request.method == "POST":
        recruiter = get_object_or_404(User, pk=pk, is_recruiter=True)
        if recruiter.recruiter_cv:
            recruiter.is_active = True
            recruiter.save(update_fields=["is_active"])
            messages.success(request, f"Đã duyệt tài khoản nhà tuyển dụng {recruiter.username}.")
        else:
            messages.error(request, "Không thể duyệt tài khoản vì chưa có CV xác minh.")

    return redirect("admin_manage_users")


@staff_member_required
def admin_manage_jobs(request):
    """Show recruiters, then one selected recruiter's chosen expiration group."""
    recruiter_id = request.GET.get("recruiter", "").strip()
    status_filter = request.GET.get("status", "").strip()
    now = timezone.now()
    recruiters = User.objects.filter(is_recruiter=True).annotate(
        job_count=Count("job", distinct=True),
        active_job_count=Count(
            "job",
            filter=Q(job__expires_at__isnull=True) | Q(job__expires_at__gte=now),
            distinct=True,
        ),
        expired_job_count=Count(
            "job", filter=Q(job__expires_at__lt=now), distinct=True
        ),
    ).order_by("username")

    if recruiter_id:
        recruiter = get_object_or_404(recruiters, pk=recruiter_id)
        recruiter_jobs = list(
            Job.objects.filter(recruiter=recruiter)
            .select_related("recruiter")
            .order_by("-created_at")
        )
        active_jobs = [job for job in recruiter_jobs if not job.is_expired_status]
        expired_jobs = [job for job in recruiter_jobs if job.is_expired_status]
        jobs = []
        if status_filter == "active":
            jobs = active_jobs
        elif status_filter == "expired":
            jobs = expired_jobs
        else:
            status_filter = ""

        return render(
            request,
            "admin/manage_jobs.html",
            {
                "selected_recruiter": recruiter,
                "recruiters": recruiters,
                "jobs": jobs,
                "status_filter": status_filter,
                "active_job_count": len(active_jobs),
                "expired_job_count": len(expired_jobs),
                "selected_recruiter_job_count": recruiter.job_count,
            },
        )

    job_summary = Job.objects.aggregate(
        total=Count("pk"),
        active=Count(
            "pk", filter=Q(expires_at__isnull=True) | Q(expires_at__gte=now)
        ),
        expired=Count("pk", filter=Q(expires_at__lt=now)),
    )
    return render(
        request,
        "admin/manage_jobs.html",
        {
            "recruiters": recruiters,
            "recruiter_count": recruiters.count(),
            "recent_recruiters": recruiters.order_by("-date_joined")[:5],
            "job_summary": job_summary,
        },
    )


@staff_member_required
def admin_update_job_status(request, pk):
    """Cập nhật trạng thái duyệt cho tin tuyển dụng"""
    job = get_object_or_404(Job, pk=pk)

    if request.method == "POST":
        new_status = request.POST.get("status")
        valid_statuses = {value for value, _ in Job._meta.get_field("status").choices}
        if new_status in valid_statuses:
            job.status = new_status
            job.save(update_fields=["status"])
            messages.success(request, "Cập nhật trạng thái tin tuyển dụng thành công!")
        else:
            messages.error(request, "Trạng thái không hợp lệ.")

    return redirect("admin_manage_jobs")


@staff_member_required
def admin_delete_job(request, pk):
    """Xóa bài tuyển dụng bất kỳ"""
    job = get_object_or_404(Job, pk=pk)
    job.delete()
    return redirect("admin_manage_jobs")


@staff_member_required
def admin_manage_applications(request):
    """Quản lý đơn ứng tuyển gom nhóm theo từng bài đăng duy nhất"""
    query = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()

    applications = Application.objects.all().order_by("-applied_at")

    if query:
        applications = applications.filter(
            Q(job__title__icontains=query) | Q(candidate__username__icontains=query)
        )

    if status_filter:
        applications = applications.filter(status=status_filter)

    job_ids = applications.values_list('job_id', flat=True).distinct()
    jobs_with_applications = Job.objects.filter(id__in=job_ids).annotate(
        total_apps=Count('applications')
    ).order_by('-id')

    total_count = applications.count()

    return render(
        request,
        "admin/manage_applications.html",
        {
            "jobs_with_applications": jobs_with_applications,
            "applications": applications,
            "total_count": total_count,
            "query": query,
            "status_filter": status_filter,
        },
    )

@staff_member_required
def admin_delete_application(request, pk):
    """Xóa đơn ứng tuyển rác"""
    application = get_object_or_404(Application, pk=pk)
    application.delete()
    messages.success(request, "Xóa đơn ứng tuyển thành công!")
    return redirect("admin_manage_applications")


# ==========================================
# CÁC VIEW QUẢN LÝ GIAO DỊCH MUA GÓI CƯỚC (ĐÃ CẬP NHẬT TÍNH TIỀN THEO THÁNG)
# ==========================================

@staff_member_required
def admin_manage_transactions(request):
    """Trang quản lý và duyệt các giao dịch mua gói cước của nhà tuyển dụng"""
    status_filter = request.GET.get("status", "").strip()
    selected_month = request.GET.get("month", "").strip() # Lấy tháng người dùng chọn (định dạng YYYY-MM)
    
    transactions = PackageTransaction.objects.all().order_by("-created_at")

    if status_filter:
        transactions = transactions.filter(status=status_filter)

    # 1. Tính tổng doanh thu toàn bộ từ các giao dịch đã duyệt (approved)
    total_approved_amount = transactions.filter(status="approved").aggregate(total=Sum('amount'))['total'] or 0

    # 2. Lấy danh sách tất cả các tháng có giao dịch để hiển thị trong thẻ chọn (dropdown)
    available_months = (
        PackageTransaction.objects.filter(status="approved")
        .annotate(month=TruncMonth('created_at'))
        .values_list('month', flat=True)
        .distinct()
        .order_by('-month')
    )

    # 3. Tính doanh thu của tháng được chọn (nếu có)
    selected_month_revenue = None
    if selected_month:
        # selected_month có dạng "YYYY-MM"
        year, month = selected_month.split('-')
        month_revenue_data = (
            transactions.filter(status="approved", created_at__year=year, created_at__month=month)
            .aggregate(total=Sum('amount'))['total']
        )
        selected_month_revenue = month_revenue_data or 0

    paginator = Paginator(transactions, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    status_choices = [
        ("pending", "Chờ xác nhận thanh toán"),
        ("approved", "Đã thanh toán / Kích hoạt"),
        ("rejected", "Từ chối"),
    ]

    return render(
        request,
        "admin/manage_transactions.html",
        {
            "page_obj": page_obj,
            "status_filter": status_filter,
            "status_choices": status_choices,
            "total_approved_amount": total_approved_amount,
            "available_months": available_months,
            "selected_month": selected_month,
            "selected_month_revenue": selected_month_revenue,
        },
    )


@staff_member_required
def admin_approve_transaction(request, pk):
    transaction = get_object_or_404(PackageTransaction, pk=pk)

    if request.method == "POST":
        if transaction.status != "approved":
            transaction.status = "approved"
            transaction.save()

            recruiter_profile, _ = RecruiterAccount.objects.get_or_create(
                user=transaction.recruiter
            )
            recruiter_profile.active_package = transaction.package

            limit = getattr(transaction.package, "post_limit", 5)
            recruiter_profile.posts_remaining = (
                getattr(recruiter_profile, "posts_remaining", 0) + limit
            )

            now = timezone.now()
            if (
                recruiter_profile.package_expires_at
                and recruiter_profile.package_expires_at > now
            ):
                recruiter_profile.package_expires_at += timedelta(
                    days=transaction.package.duration_days
                )
            else:
                recruiter_profile.package_expires_at = now + timedelta(
                    days=transaction.package.duration_days
                )

            recruiter_profile.save()

            messages.success(
                request,
                f"Đã duyệt giao dịch #{transaction.id} và kích hoạt gói cước thành công!",
            )
        else:
            messages.warning(request, "Giao dịch này đã được duyệt trước đó.")

    return redirect("admin_manage_transactions")

@staff_member_required
def admin_reject_transaction(request, pk):
    """Từ chối giao dịch mua gói cước"""
    transaction = get_object_or_404(PackageTransaction, pk=pk)

    if request.method == "POST":
        if transaction.status != "rejected":
            transaction.status = "rejected"
            transaction.save()
            messages.success(request, f"Đã từ chối giao dịch #{transaction.id}.")
        else:
            messages.warning(request, "Giao dịch này đã bị từ chối trước đó.")

    return redirect("admin_manage_transactions")


# ==========================================
# CÁC VIEW LIÊN HỆ VÀ HỖ TRỢ
# ==========================================

def contact_view(request):
    if request.method == "POST":
        name = request.POST.get("name")
        email = request.POST.get("email")
        message_content = request.POST.get("message")

        if name and email and message_content:
            ContactMessage.objects.create(
                name=name,
                email=email,
                message=message_content,
            )

            try:
                send_mail(
                    subject=f"[Yêu cầu hỗ trợ mới] Từ khách hàng: {name}",
                    message=(
                        "Bạn nhận được một yêu cầu hỗ trợ mới từ hệ thống CTJob:\n\n"
                        f"- Họ và tên: {name}\n"
                        f"- Email: {email}\n"
                        f"- Nội dung: {message_content}\n\n"
                        "Vui lòng truy cập trang Quản trị Admin để phản hồi."
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[settings.EMAIL_HOST_USER],
                    fail_silently=False,
                )
            except Exception as e:
                print(f"Lỗi gửi email: {e}")

            messages.success(
                request,
                "Gửi câu hỏi thành công! Bộ phận hỗ trợ sẽ phản hồi qua email cho bạn.",
            )

        return redirect("contact")

    return render(request, "pages/contact.html")


@staff_member_required
def admin_reply_contact(request, pk):
    contact = get_object_or_404(ContactMessage, pk=pk)
    if request.method == "POST":
        reply_message = request.POST.get("reply_message")
        if reply_message:
            try:
                send_mail(
                    subject="Phản hồi từ hỗ trợ CTJob về yêu cầu của bạn",
                    message=reply_message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[contact.email],
                    fail_silently=False,
                )
                if hasattr(contact, 'is_replied'):
                    contact.is_replied = True
                    contact.save(update_fields=['is_replied'])

                messages.success(request, f"Đã gửi phản hồi thành công đến {contact.email}")
            except Exception as e:
                messages.error(request, f"Lỗi khi gửi email: {str(e)}")
        return redirect("custom_admin_dashboard")

    return render(request, "admin/admin_reply_contact.html", {"contact": contact})


def admin_reply_contact_action(request, pk):
    if request.method == "POST":
        contact = get_object_or_404(ContactMessage, pk=pk)
        reply_content = request.POST.get("reply_content")

        if reply_content:
            try:
                send_mail(
                    subject="Phản hồi từ hỗ trợ CTJob",
                    message=reply_content,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[contact.email],
                    fail_silently=False,
                )
                
                if hasattr(contact, 'is_replied'):
                    contact.is_replied = True
                    contact.save(update_fields=['is_replied'])

                messages.success(
                    request,
                    f"Đã gửi email trả lời thành công cho {contact.name}!",
                )
            except Exception as e:
                messages.error(
                    request,
                    f"Lỗi gửi email: {str(e)}",
                )

        return redirect("custom_admin_dashboard")
    return redirect("custom_admin_dashboard")


@staff_member_required
def admin_delete_resolved_contacts(request):
    """Xóa tất cả các yêu cầu hỗ trợ đã được xử lý/phản hồi"""
    if request.method == "POST":
        if hasattr(ContactMessage, 'is_replied'):
            resolved_messages = ContactMessage.objects.filter(is_replied=True)
        else:
            resolved_messages = ContactMessage.objects.none()
            
        count = resolved_messages.count()
        resolved_messages.delete()
        
        messages.success(request, f"Đã xóa thành công {count} yêu cầu hỗ trợ đã xử lý!")
    return redirect("custom_admin_dashboard")