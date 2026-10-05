from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import ApplicationForm
from .models import Application, HIRING_CAPACITY_STATUSES, Job, JobChatMessage
from .services import (
    send_application_status_email,
    send_interview_reminder_email,
)


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

    # Lấy lịch hiện tại để hiển thị trên form.
    parsed = parse_interview_details(application.interview_details)
    interview_date = parsed.get("date", "")
    interview_time = parsed.get("time", "")
    interview_note = parsed.get("note", "")

    if request.method == "POST":
        status = request.POST.get("status")
        interview_date = request.POST.get("interview_date", "").strip()
        interview_time = request.POST.get("interview_time", "").strip()
        interview_note = request.POST.get("interview_note", "").strip()

        valid_statuses = {
            value for value, _ in Application._meta.get_field("status").choices
        }
        if status not in valid_statuses:
            messages.error(request, "Trạng thái hồ sơ không hợp lệ.")
            return redirect("job_applications", pk=application.job.pk)

        schedule_statuses = {"Approved", "InterviewPassed", "Trial", "Hired"}
        if status not in schedule_statuses:
            interview_date = ""
            interview_time = ""
            interview_note = ""
        if status == "Approved" and (not interview_date or not interview_time):
            messages.error(
                request,
                "Khi duyệt phỏng vấn, vui lòng nhập ngày và giờ hẹn để ứng viên nhận được lịch.",
            )
            return render(
                request,
                "jobs/update_application.html",
                {
                    "application": application,
                    "interview_date": interview_date,
                    "interview_time": interview_time,
                    "interview_note": interview_note,
                    "selected_status": status,
                    "status_error": "Cần nhập ngày và giờ hẹn trước khi duyệt phỏng vấn.",
                },
            )

        with transaction.atomic():
            job = Job.objects.select_for_update().get(pk=application.job_id)
            application = Application.objects.select_for_update().get(pk=application.pk)
            previous_status = application.status
            if (
                status in HIRING_CAPACITY_STATUSES
                and application.status not in HIRING_CAPACITY_STATUSES
            ):
                current_hires = Application.objects.filter(
                    job=job,
                    status__in=HIRING_CAPACITY_STATUSES,
                ).count()
                if current_hires >= job.max_hires:
                    messages.error(
                        request,
                        f'Tin này đã đủ chỉ tiêu nhận {job.max_hires} người. '
                        'Hãy tăng chỉ tiêu hoặc chuyển một hồ sơ khác khỏi trạng thái thử việc/đã nhận.',
                    )
                    return render(
                        request,
                        "jobs/update_application.html",
                        {
                            "application": application,
                            "interview_date": interview_date,
                            "interview_time": interview_time,
                            "interview_note": interview_note,
                            "selected_status": status,
                        },
                    )

            application.status = status
            application.interview_details = build_interview_details(
                interview_date,
                interview_time,
                interview_note,
            )
            application.reminder_sent = False
            application.save()

            status_display = application.get_status_display()
            if previous_status != status:
                schedule_label = (
                    "Lịch phỏng vấn"
                    if status == "Approved"
                    else "Lịch bắt đầu thử việc/đi làm"
                )
                msg_content = (
                    f"Hồ sơ ứng tuyển vị trí '{job.title}' của bạn đã được cập nhật "
                    f"trạng thái: {status_display}."
                )
                if application.interview_details:
                    msg_content += (
                        f"\n{schedule_label}:\n{application.interview_details}"
                    )

                JobChatMessage.objects.create(
                    job=job,
                    sender=request.user,
                    receiver=application.candidate,
                    sender_name=request.user.username,
                    receiver_name=application.candidate.username,
                    message=msg_content,
                    is_read=False,
                    is_application_update=True,
                )

        if previous_status != status:
            try:
                send_application_status_email(application)
            except Exception as error:
                messages.warning(
                    request,
                    f"Trạng thái đã được lưu và ứng viên vẫn nhận thông báo trong trang web, "
                    f"nhưng không gửi được email: {error}",
                )

        # Thông báo phản hồi giao diện
        if status == "Approved" and interview_date:
            messages.success(request, "Đã lưu trạng thái phê duyệt và lịch hẹn phỏng vấn thành công.")
        elif status == "Rejected":
            messages.info(request, "Đã cập nhật trạng thái từ chối.")
        elif previous_status == status:
            messages.success(request, "Thông tin hồ sơ đã được lưu.")
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
            "selected_status": application.status,
        },
    )

@login_required
def candidate_applications(request):
    applications = Application.objects.filter(candidate=request.user).order_by("-applied_at")
    notifications = list(
        JobChatMessage.objects.filter(
            receiver=request.user,
            is_application_update=True,
            is_read=False,
        ).select_related("job").order_by("-created_at")
    )

    for app in applications:
        if app.needs_interview_reminder and not app.reminder_sent:
            try:
                send_interview_reminder_email(app)
            except Exception:
                messages.error(
                    request,
                    f"Không gửi được email nhắc lịch cho hồ sơ '{app.job.title}'. "
                    "Vui lòng kiểm tra cấu hình Gmail SMTP.",
                )

    if notifications:
        JobChatMessage.objects.filter(
            pk__in=[notification.pk for notification in notifications],
            receiver=request.user,
            is_application_update=True,
            is_read=False,
        ).update(is_read=True)

    return render(
        request,
        "jobs/candidate_applications.html",
        {
            "applications": applications,
            "notifications": notifications,
        },
    )