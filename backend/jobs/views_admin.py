import mimetypes
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q, Sum
from django.db.models.functions import TruncMonth
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from .models import (
    Application,
    ContactMessage,
    Job,
    PackageTransaction,
    RecruiterAccount,
)


@staff_member_required
def custom_admin_dashboard(request):
    """Trang chủ Admin: Thống kê tổng quan hệ thống và hiển thị tin nhắn hỗ trợ"""
    total_jobs = Job.objects.count()
    total_applications = Application.objects.count()
    total_users = User.objects.count()
    users = User.objects.select_related(
        "profile", "company_profile"
    ).order_by("-date_joined")[:5]
    contact_query = request.GET.get("q", "").strip()
    contact_status = request.GET.get("contact_status", "").strip()
    contact_messages = ContactMessage.objects.all().order_by("-created_at")
    if contact_query:
        contact_messages = contact_messages.filter(
            Q(name__icontains=contact_query)
            | Q(email__icontains=contact_query)
            | Q(message__icontains=contact_query)
        )
    if contact_status == "pending":
        contact_messages = contact_messages.filter(is_replied=False)
    elif contact_status == "replied":
        contact_messages = contact_messages.filter(is_replied=True)

    pending_contact_count = ContactMessage.objects.filter(is_replied=False).count()
    contact_paginator = Paginator(contact_messages, 10)
    contact_page = contact_paginator.get_page(request.GET.get("contact_page"))

    context = {
        "total_jobs": total_jobs,
        "total_applications": total_applications,
        "total_users": total_users,
        "users": users,
        "contact_messages": contact_page,
        "contact_page": contact_page,
        "contact_query": contact_query,
        "contact_status": contact_status,
        "contact_message_count": contact_paginator.count,
        "pending_contact_count": pending_contact_count,
    }
    return render(request, "admin/custom_dashboard.html", context)


@staff_member_required
def admin_manage_users(request):
    """Trang quản lý danh sách tài khoản theo từng phân loại (Admin, Nhà tuyển dụng, Ứng viên)"""
    query = request.GET.get("q", "").strip()
    role_filter = request.GET.get("role", "").strip()
    status_filter = request.GET.get("status", "").strip()

    # Nếu truy cập vào trang mà chưa chọn role_filter, mặc định chọn 'candidate' (hoặc nhóm bạn muốn)
    if not role_filter:
        role_filter = "candidate"

    base_users = User.objects.all()
    
    # Tính toán số lượng cho từng loại (để hiển thị badge ở sidebar)
    admin_count = base_users.filter(Q(is_staff=True) | Q(is_superuser=True)).count()
    recruiter_count = base_users.filter(is_recruiter=True).count()
    candidate_count = base_users.filter(is_candidate=True).count()

    # Lọc danh sách user theo nhóm được chọn
    user_list = base_users.select_related(
        "profile", "company_profile"
    ).order_by("-date_joined")
    role_users = base_users
    if role_filter == "candidate":
        user_list = user_list.filter(is_candidate=True)
        role_users = role_users.filter(is_candidate=True)
    elif role_filter == "recruiter":
        user_list = user_list.filter(is_recruiter=True)
        role_users = role_users.filter(is_recruiter=True)
    elif role_filter == "admin":
        user_list = user_list.filter(Q(is_staff=True) | Q(is_superuser=True))
        role_users = role_users.filter(Q(is_staff=True) | Q(is_superuser=True))
    elif role_filter != "all":
        role_filter = "all"

    active_count = role_users.filter(is_active=True).count()
    inactive_count = role_users.filter(is_active=False).count()

    # Tìm kiếm theo tên hoặc email nếu có
    if query:
        user_list = user_list.filter(
            Q(username__icontains=query)
            | Q(email__icontains=query)
            | Q(company_profile__company_name__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(profile__candidate_name__icontains=query)
        )
    if status_filter == "active":
        user_list = user_list.filter(is_active=True)
    elif status_filter == "inactive":
        user_list = user_list.filter(is_active=False)

    paginator = Paginator(user_list, 10)
    page_number = request.GET.get("page")
    users = paginator.get_page(page_number)

    # Tổng số tài khoản của riêng nhóm đang lọc
    total_count = paginator.count

    return render(
        request,
        "admin/manage_users.html",
        {
            "users": users,
            "query": query,
            "role_filter": role_filter,
            "status_filter": status_filter,
            "admin_count": admin_count,
            "recruiter_count": recruiter_count,
            "candidate_count": candidate_count,
            "total_count": total_count,
            "active_count": active_count,
            "inactive_count": inactive_count,
        },
    )

@staff_member_required
def admin_delete_user(request, pk):
    """Xóa tài khoản người dùng"""
    user_to_delete = get_object_or_404(User, pk=pk)
    if request.method == "POST" and user_to_delete != request.user:
        username = user_to_delete.username
        user_to_delete.delete()
        messages.success(request, f"Đã xóa tài khoản {username}.")
    elif request.method == "POST":
        messages.error(request, "Không thể xóa tài khoản admin đang đăng nhập.")
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
    """Admin duyệt tài khoản nhà tuyển dụng, lưu thời gian và gửi email thông báo"""
    if request.method == "POST":
        recruiter = get_object_or_404(User, pk=pk, is_recruiter=True)
        company_profile = getattr(recruiter, 'company_profile', None)
        
        if recruiter.recruiter_cv and company_profile:
            recruiter.is_active = True
            recruiter.save(update_fields=["is_active"])
            
            # Cập nhật trạng thái duyệt và thời gian duyệt
            company_profile.is_approved = True
            company_profile.approved_at = timezone.now()
            company_profile.save(update_fields=["is_approved", "approved_at"])
            
            try:
                sent_count = send_mail(
                    subject="Thông báo: Tài khoản Nhà tuyển dụng đã được phê duyệt - CTJob",
                    message=(
                        f"Xin chào {recruiter.get_full_name() or recruiter.username},\n\n"
                        f"Tài khoản Nhà tuyển dụng của công ty '{company_profile.company_name}' trên hệ thống CTJob đã được Admin PHÊ DUYỆT vào lúc {company_profile.approved_at.strftime('%d/%m/%Y %H:%M')}.\n"
                        f"Bây giờ bạn có thể đăng nhập để đăng tin tuyển dụng và tìm kiếm ứng viên.\n\n"
                        f"Trân trọng,\nĐội ngũ quản trị CTJob"
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[recruiter.email],
                    fail_silently=False,
                )
                if sent_count != 1:
                    raise RuntimeError("Django không xác nhận đã gửi email.")
            except Exception as error:
                messages.warning(
                    request,
                    f"Đã duyệt tài khoản nhưng không gửi được email đến {recruiter.email}: {error}",
                )
            else:
                messages.success(
                    request,
                    f"Đã duyệt tài khoản và gửi email thông báo cho {recruiter.email}.",
                )
        else:
            messages.error(request, "Không thể duyệt tài khoản vì thiếu CV xác minh hoặc chưa có hồ sơ công ty.")

    return redirect("admin_manage_users")


@staff_member_required
def admin_reject_recruiter(request, pk):
    """Admin từ chối tài khoản nhà tuyển dụng và gửi email thông báo"""
    if request.method == "POST":
        recruiter = get_object_or_404(User, pk=pk, is_recruiter=True)
        company_profile = getattr(recruiter, 'company_profile', None)
        
        if company_profile:
            company_profile.is_approved = False
            company_profile.approved_at = None
            company_profile.save(update_fields=["is_approved", "approved_at"])
            recruiter.is_active = False
            recruiter.save(update_fields=["is_active"])
            
            # GỬI EMAIL THÔNG BÁO TỪ CHỐI
            try:
                send_mail(
                    subject="Thông báo: Tài khoản Nhà tuyển dụng không được phê duyệt - CTJob",
                    message=(
                        f"Xin chào {recruiter.get_full_name() or recruiter.username},\n\n"
                        f"Rất tiếc, tài khoản Nhà tuyển dụng của bạn trên hệ thống CTJob đã bị TỪ CHỐI sau khi kiểm tra hồ sơ xác minh.\n"
                        f"Vui lòng liên hệ với bộ phận hỗ trợ nếu bạn cần giải đáp thêm.\n\n"
                        f"Trân trọng,\nĐội ngũ quản trị CTJob"
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[recruiter.email],
                    fail_silently=False,
                )
            except Exception as e:
                print(f"Lỗi gửi email từ chối: {e}")

            messages.warning(request, f"Đã từ chối và gửi email thông báo cho nhà tuyển dụng {recruiter.username}.")
            
    return redirect("admin_manage_users")


@staff_member_required
def admin_manage_jobs(request):
    """Show recruiters, then one selected recruiter's chosen expiration group."""
    recruiter_id = request.GET.get("recruiter", "").strip()
    section = request.GET.get("section", "").strip()
    status_filter = request.GET.get("status", "").strip()
    if section not in {"active", "expired", "packages"}:
        section = status_filter if status_filter in {"active", "expired"} else "active"
    status_filter = section if section in {"active", "expired"} else ""
    query = request.GET.get("q", "").strip()
    now = timezone.now()
    all_jobs_view = request.GET.get("all") == "1"
    all_recruiters = User.objects.filter(is_recruiter=True).select_related(
        "company_profile"
    ).annotate(
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
        recruiter = get_object_or_404(all_recruiters, pk=recruiter_id)
        try:
            package_account = recruiter.recruiter_account
        except RecruiterAccount.DoesNotExist:
            package_account = None
        package_history = list(
            PackageTransaction.objects.filter(recruiter=recruiter)
            .select_related("package")
            .order_by("-created_at")
        )
        total_purchased_posts = (
            package_account.total_posts_purchased if package_account else 0
        )
        usable_package_posts = (
            max(package_account.posts_remaining, 0)
            if package_account
            and package_account.package_expires_at
            and package_account.package_expires_at > now
            else 0
        )
        if package_account:
            package_account.usable_package_posts = usable_package_posts
            package_account.total_usable_posts = (
                max(package_account.free_posts_left, 0) + usable_package_posts
            )
        all_recruiter_jobs = Job.objects.filter(recruiter=recruiter).select_related(
            "recruiter__company_profile"
        )
        active_job_count = all_recruiter_jobs.filter(
            Q(expires_at__isnull=True) | Q(expires_at__gte=now)
        ).count()
        expired_job_count = all_recruiter_jobs.filter(expires_at__lt=now).count()
        jobs = all_recruiter_jobs.order_by("-created_at")
        if section == "active":
            jobs = jobs.filter(Q(expires_at__isnull=True) | Q(expires_at__gte=now))
        elif section == "expired":
            jobs = jobs.filter(expires_at__lt=now)
        if query and section != "packages":
            jobs = jobs.filter(
                Q(title__icontains=query) | Q(company_name__icontains=query)
            )

        job_page = Paginator(jobs, 10).get_page(request.GET.get("page"))
        return render(
            request,
            "admin/manage_jobs.html",
            {
                "selected_recruiter": recruiter,
                "recruiters": all_recruiters,
                "jobs": job_page,
                "job_page": job_page,
                "status_filter": status_filter,
                "section": section,
                "query": query,
                "active_job_count": active_job_count,
                "expired_job_count": expired_job_count,
                "selected_recruiter_job_count": recruiter.job_count,
                "all_jobs_view": all_jobs_view,
                "package_account": package_account,
                "package_history": package_history,
                "total_purchased_posts": total_purchased_posts,
                "now": now,
            },
        )

    job_summary = Job.objects.aggregate(
        total=Count("pk"),
        active=Count(
            "pk", filter=Q(expires_at__isnull=True) | Q(expires_at__gte=now)
        ),
        expired=Count("pk", filter=Q(expires_at__lt=now)),
    )
    if all_jobs_view:
        jobs = Job.objects.select_related(
            "recruiter__company_profile"
        ).order_by("-created_at")
        if status_filter == "active":
            jobs = jobs.filter(Q(expires_at__isnull=True) | Q(expires_at__gte=now))
        elif status_filter == "expired":
            jobs = jobs.filter(expires_at__lt=now)
        else:
            status_filter = ""
        if query:
            jobs = jobs.filter(
                Q(title__icontains=query)
                | Q(company_name__icontains=query)
                | Q(recruiter__company_profile__company_name__icontains=query)
            )
        job_page = Paginator(jobs, 10).get_page(request.GET.get("page"))
        return render(
            request,
            "admin/manage_jobs.html",
            {
                "recruiters": all_recruiters,
                "jobs": job_page,
                "job_page": job_page,
                "query": query,
                "status_filter": status_filter,
                "job_summary": job_summary,
                "all_jobs_view": True,
            },
        )

    recruiters = all_recruiters
    if query:
        recruiters = recruiters.filter(
            Q(username__icontains=query) | Q(email__icontains=query)
            | Q(company_profile__company_name__icontains=query)
        )
    recruiter_page = Paginator(recruiters.order_by("-date_joined"), 10).get_page(
        request.GET.get("page")
    )
    recruiter_page.object_list = list(
        recruiter_page.object_list.select_related(
            "company_profile",
            "recruiter_account__active_package",
        ).prefetch_related(
            Prefetch(
                "packagetransaction_set",
                queryset=PackageTransaction.objects.select_related("package").order_by(
                    "-created_at"
                ),
                to_attr="package_history",
            ),
            Prefetch(
                "job_set",
                queryset=Job.objects.order_by("-created_at"),
                to_attr="recruiter_jobs",
            ),
        )
    )
    now = timezone.now()
    for recruiter in recruiter_page:
        try:
            package_account = recruiter.recruiter_account
        except RecruiterAccount.DoesNotExist:
            package_account = None
        recruiter.package_account = package_account
        recruiter.package_history = getattr(recruiter, "package_history", [])
        recruiter.recruiter_jobs = getattr(recruiter, "recruiter_jobs", [])
        if package_account:
            package_account.usable_package_posts = (
                max(package_account.posts_remaining, 0)
                if package_account.package_expires_at
                and package_account.package_expires_at > now
                else 0
            )
            package_account.total_usable_posts = (
                max(package_account.free_posts_left, 0)
                + package_account.usable_package_posts
            )
            package_account.approved_purchase_count = sum(
                transaction.status == "approved"
                for transaction in recruiter.package_history
            )
    return render(
        request,
        "admin/manage_jobs.html",
        {
            "recruiters": all_recruiters,
            "recruiter_page": recruiter_page,
            "query": query,
            "recruiter_count": recruiters.count(),
            "job_summary": job_summary,
            "now": now,
        },
    )


@staff_member_required
def admin_delete_job(request, pk):
    """Xóa bài tuyển dụng bất kỳ"""
    job = get_object_or_404(Job, pk=pk)
    recruiter_id = job.recruiter_id
    if request.method == "POST":
        title = job.title
        job.delete()
        messages.success(request, f"Đã xóa tin tuyển dụng “{title}”.")
    return_all = request.POST.get("return_all") == "1"
    return_recruiter = request.POST.get("return_recruiter", "").strip()
    query_params = {}
    if return_recruiter.isdigit():
        query_params["recruiter"] = return_recruiter
    elif not return_all:
        query_params["recruiter"] = recruiter_id
    if return_all:
        query_params["all"] = "1"
    return_status = request.POST.get("return_status", "")
    return_query = request.POST.get("return_q", "").strip()
    if return_status in {"active", "expired"}:
        query_params["status"] = return_status
    if return_query:
        query_params["q"] = return_query
    return redirect(f"{reverse('admin_manage_jobs')}?{urlencode(query_params)}")


@staff_member_required
def admin_manage_applications(request):
    """Quản lý đơn ứng tuyển gom nhóm theo từng bài đăng duy nhất"""
    query = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()

    applications = Application.objects.select_related(
        "job__recruiter__company_profile", "candidate__profile"
    ).order_by("-applied_at")

    if query:
        applications = applications.filter(
            Q(job__title__icontains=query)
            | Q(job__company_name__icontains=query)
            | Q(candidate__username__icontains=query)
            | Q(candidate__email__icontains=query)
            | Q(candidate__first_name__icontains=query)
            | Q(candidate__last_name__icontains=query)
            | Q(candidate__profile__candidate_name__icontains=query)
        )

    if status_filter:
        applications = applications.filter(status=status_filter)

    total_count = applications.count()
    application_stats = Application.objects.aggregate(
        pending=Count("pk", filter=Q(status="Pending")),
        approved=Count("pk", filter=Q(status="Approved")),
        interview_passed=Count("pk", filter=Q(status="InterviewPassed")),
        trial=Count("pk", filter=Q(status="Trial")),
        hired=Count("pk", filter=Q(status="Hired")),
        rejected=Count("pk", filter=Q(status="Rejected")),
    )
    filtered_job_ids = applications.values_list("job_id", flat=True).distinct()
    jobs_with_applications = (
        Job.objects.filter(id__in=filtered_job_ids)
        .select_related("recruiter__company_profile")
        .annotate(
            total_apps=Count(
                "applications", filter=Q(applications__in=applications)
            )
        )
        .order_by("-id")
    )
    job_page = Paginator(jobs_with_applications, 10).get_page(
        request.GET.get("page")
    )
    page_job_ids = list(job_page.object_list.values_list("pk", flat=True))
    applications = applications.filter(job_id__in=page_job_ids)

    return render(
        request,
        "admin/manage_applications.html",
        {
            "jobs_with_applications": job_page,
            "job_page": job_page,
            "applications": applications,
            "total_count": total_count,
            "application_stats": application_stats,
            "application_status_choices": Application._meta.get_field(
                "status"
            ).choices,
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
    query = request.GET.get("q", "").strip()
    
    all_transactions = PackageTransaction.objects.all()
    transactions = all_transactions.select_related(
        "recruiter__company_profile",
        "package",
    ).order_by("-created_at")

    if status_filter:
        transactions = transactions.filter(status=status_filter)
    if query:
        transactions = transactions.filter(
            Q(recruiter__username__icontains=query)
            | Q(recruiter__email__icontains=query)
            | Q(package__name__icontains=query)
            | Q(payment_code__icontains=query)
            | Q(sepay_transaction_id__icontains=query)
        )

    transaction_stats = all_transactions.aggregate(
        total=Count("pk"),
        pending=Count("pk", filter=Q(status="pending")),
        approved=Count("pk", filter=Q(status="approved")),
        rejected=Count("pk", filter=Q(status="rejected")),
        revenue=Sum("amount", filter=Q(status="approved")),
    )
    total_approved_amount = transaction_stats["revenue"] or 0

    # 2. Lấy danh sách tất cả các tháng có giao dịch để hiển thị trong thẻ chọn (dropdown)
    available_months = (
        all_transactions.filter(status="approved")
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
            all_transactions.filter(status="approved", created_at__year=year, created_at__month=month)
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
            "query": query,
            "status_choices": status_choices,
            "total_approved_amount": total_approved_amount,
            "available_months": available_months,
            "selected_month": selected_month,
            "selected_month_revenue": selected_month_revenue,
            "transaction_stats": transaction_stats,
        },
    )


@staff_member_required
def admin_reject_transaction(request, pk):
    """Từ chối giao dịch mua gói cước"""
    transaction = get_object_or_404(PackageTransaction, pk=pk)

    if request.method == "POST":
        if transaction.status == "pending":
            transaction.status = "rejected"
            transaction.save()
            messages.success(request, f"Đã từ chối giao dịch #{transaction.id}.")
        elif transaction.status == "approved":
            messages.warning(
                request,
                "Giao dịch đã được SePay xác nhận và kích hoạt, không thể từ chối.",
            )
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