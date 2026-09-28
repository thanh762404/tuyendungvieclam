from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import ApplicationForm
from .models import Application, Job, JobChatMessage


def parse_interview_details(interview_details):
    result = {"date": "", "time": "", "note": ""}
    if not interview_details:
        return result

    for line in interview_details.splitlines():
        if line.lower().startswith("ngày:"):
            result["date"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("giờ:"):
            result["time"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("nội dung:"):
            result["note"] = line.split(":", 1)[1].strip()

    return result


def build_interview_details(interview_date, interview_time, interview_note):
    details = []
    if interview_date:
        details.append(f"Ngày: {interview_date}")
    if interview_time:
        details.append(f"Giờ: {interview_time}")
    if interview_note:
        details.append(f"Nội dung/Địa điểm: {interview_note}")
    return "\n".join(details)


def get_recruiter_display_info(recruiter_user):
    """Hàm hỗ trợ lấy tên hiển thị và email của Nhà tuyển dụng"""
    employer_profile = getattr(recruiter_user, 'profile', None)
    
    # Lấy tên hiển thị của nhà tuyển dụng (ưu tiên full_name/company_name trong profile, nếu không có lấy username)
    recruiter_name = recruiter_user.username
    if employer_profile:
        recruiter_name = getattr(employer_profile, 'company_name', None) or getattr(employer_profile, 'full_name', None) or recruiter_user.username
        
    recruiter_email = getattr(employer_profile, 'email', None) or getattr(recruiter_user, 'email', '')
    return recruiter_name, recruiter_email


@login_required
def my_applications_view(request):
    applications = Application.objects.filter(candidate=request.user)
    return render(request, "jobs/my_applications.html", {"applications": applications})


@login_required
def apply_job(request, pk):
    job = get_object_or_404(Job, pk=pk)

    if job.is_expired_status:
        messages.error(
            request, "Tin tuyển dụng này đã hết hạn, bạn không thể ứng tuyển."
        )
        return redirect("job_detail", pk=job.pk)

    if request.method == "POST":
        form = ApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            application = form.save(commit=False)
            application.job = job
            application.candidate = request.user
            application.save()
            return render(request, "jobs/apply_success.html", {"job": job})
    else:
        form = ApplicationForm()
    return render(request, "jobs/apply_form.html", {"job": job, "form": form})


@login_required
def job_applications(request, pk):
    job = get_object_or_404(Job, pk=pk, recruiter=request.user)
    applications = job.applications.all().order_by("-applied_at")
    return render(
        request,
        "jobs/job_applications.html",
        {
            "job": job,
            "applications": applications,
        },
    )


@login_required
def update_application_status(request, pk):
    application = get_object_or_404(Application, pk=pk)

    # Kiểm tra quyền nhà tuyển dụng sở hữu tin tuyển dụng này không
    if application.job.recruiter != request.user:
        return render(request, "403.html", status=403)

    # Lấy thông tin lịch phỏng vấn hiện tại để hiển thị lên form GET
    parsed = parse_interview_details(application.interview_details)
    interview_date = parsed.get("date", "")
    interview_time = parsed.get("time", "")
    interview_note = parsed.get("note", "")

    if request.method == "POST":
        status = request.POST.get("status")
        interview_date = request.POST.get("interview_date", "").strip()
        interview_time = request.POST.get("interview_time", "").strip()
        interview_note = request.POST.get("interview_note", "").strip()

        # Cập nhật trạng thái đơn ứng tuyển nếu có chọn
        if status:
            application.status = status

        # Xây dựng chuỗi chi tiết lịch phỏng vấn từ form
        application.interview_details = build_interview_details(
            interview_date,
            interview_time,
            interview_note,
        )
        
        # Reset lại cờ reminder_sent để hệ thống bắt đầu theo dõi thời gian 24h tới
        application.reminder_sent = False
        application.save()

        # ==========================================
        # 1. TỰ ĐỘNG GỬI TIN NHẮN CHAT CHO ỨNG VIÊN
        # ==========================================
        status_display = "Đã duyệt / Phỏng vấn" if status == "Approved" else ("Từ chối" if status == "Rejected" else "Đang chờ duyệt")
        msg_content = f"Hồ sơ ứng tuyển vị trí '{application.job.title}' của bạn đã được cập nhật trạng thái: {status_display}."
        if interview_date:
            t_str = f" lúc {interview_time}" if interview_time else ""
            msg_content += f"\nLịch hẹn: Ngày {interview_date}{t_str}."
        if interview_note:
            msg_content += f"\nNội dung/Địa điểm: {interview_note}"

        JobChatMessage.objects.create(
            job=application.job,
            sender=request.user,
            receiver=application.candidate,
            sender_name=request.user.username,
            receiver_name=application.candidate.username,
            message=msg_content,
            is_read=False
        )

        # LƯU Ý: Đã lược bỏ việc gửi email ngay tại đây. 
        # Email nhắc nhở sẽ tự động được gửi khi thời gian đến gần trong vòng 24h tại hàm candidate_applications.

        # Thông báo phản hồi giao diện
        if status == "Approved" and interview_date:
            messages.success(request, "Đã lưu trạng thái phê duyệt và lịch hẹn thành công (Hệ thống sẽ tự động gửi email nhắc nhở ứng viên trước 24h).")
        elif status == "Rejected":
            messages.info(request, "Đã cập nhật trạng thái từ chối.")
        else:
            messages.success(request, "Đã cập nhật trạng thái ứng viên thành công.")

        return redirect("job_applications", pk=application.job.pk)

    return render(
        request,
        "jobs/update_application.html",
        {
            "application": application,
            "interview_date": interview_date,
            "interview_time": interview_time,
            "interview_note": interview_note,
        },
    )

@login_required
def candidate_applications(request):
    applications = Application.objects.filter(candidate=request.user).order_by("-applied_at")

    for app in applications:
        # Hệ thống quét: Chỉ gửi khi lịch hẹn còn trong vòng 24h tới VÀ chưa từng gửi email nhắc nhở trước đó
        if app.needs_interview_reminder and not app.reminder_sent:
            try:
                candidate_email = getattr(request.user, 'email', None)
                if candidate_email:
                    recruiter_user = app.job.recruiter
                    recruiter_name, recruiter_email = get_recruiter_display_info(recruiter_user)

                    subject = f"[CTJob] Nhắc nhở lịch phỏng vấn sắp tới trong 24h - {app.job.title}"
                    message = (
                        f"Xin chào {request.user.username},\n\n"
                        f"{app.interview_reminder_message}\n\n"
                        f"Chi tiết lịch hẹn:\n{app.interview_details}\n\n"
                        f"Vui lòng chuẩn bị kỹ và đến đúng thời gian quy định.\n\n"
                        f"Trân trọng,\n"
                        f"Nhà tuyển dụng: {recruiter_name}\n"
                        f"Email liên hệ: {recruiter_email if recruiter_email else 'Không có'}\n"
                        f"Hệ thống tuyển dụng CTJob"
                    )

                    send_mail(
                        subject=subject,
                        message=message,
                        from_email=None,
                        recipient_list=[candidate_email],
                        fail_silently=False,
                    )

                    # Đánh dấu đã gửi thành công để không bị gửi lặp lại
                    app.reminder_sent = True
                    app.save(update_fields=['reminder_sent'])
                    print(f"Đã gửi email nhắc lịch 24h thành công tới ứng viên: {candidate_email}")
            except Exception as e:
                print("Lỗi tự động gửi email nhắc lịch phỏng vấn:", e)

    return render(
        request,
        "jobs/candidate_applications.html",
        {
            "applications": applications,
        },
    )