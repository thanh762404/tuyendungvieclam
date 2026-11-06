from datetime import datetime, timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import ApplicationForm
from .models import (
    Application,
    HIRING_CAPACITY_STATUSES,
    Job,
    JobChatMessage,
    Notification,
)
from .services import (
    send_application_status_email,
    send_interview_reminder_email,
)

INTERVIEW_HOUR_CHOICES = tuple(
    (f"{hour:02d}", f"{hour:02d}") for hour in range(1, 13)
)
INTERVIEW_MINUTE_CHOICES = tuple(
    (f"{minute:02d}", f"{minute:02d}") for minute in range(60)
)


def parse_interview_details(interview_details):
    result = {"date": "", "time": "", "location": "", "note": ""}
    if not interview_details:
        return result

    lines = interview_details.splitlines()
    for index, line in enumerate(lines):
        normalized_line = line.strip().lower()
        if normalized_line.startswith("ngày:"):
            result["date"] = line.split(":", 1)[1].strip()
        elif normalized_line.startswith("giờ:"):
            result["time"] = line.split(":", 1)[1].strip()
        elif normalized_line.startswith(("địa điểm:", "địa điểm hẹn:")):
            result["location"] = line.split(":", 1)[1].strip()
        elif normalized_line.startswith(
            ("ghi chú:", "nội dung:", "nội dung/địa điểm:")
        ):
            note_lines = [line.split(":", 1)[1].strip(), *lines[index + 1 :]]
            result["note"] = "\n".join(note_lines).strip()
            break
    return result


def build_interview_details(
    interview_date, interview_time, interview_location, interview_note
):
    details = []
    if interview_date:
        details.append(f"Ngày: {interview_date}")
    if interview_time:
        details.append(f"Giờ: {interview_time}")
    if interview_location:
        details.append(f"Địa điểm: {interview_location}")
    if interview_note:
        note_lines = interview_note.splitlines()
        details.append(f"Ghi chú: {note_lines[0]}")
        details.extend(note_lines[1:])
    return "\n".join(details)


def _normalize_interview_time(value, period=""):
    value = (value or "").strip()
    period = (period or "").strip().upper()
    if not value:
        return ""
    try:
        parsed_time = datetime.strptime(value, "%H:%M")
    except ValueError:
        return None

    if not period:
        return parsed_time.strftime("%H:%M")
    if period not in {"AM", "PM"}:
        return None

    hour = parsed_time.hour
    if hour > 12:
        return None
    if period == "PM" and hour < 12:
        hour += 12
    elif period == "AM" and hour == 12:
        hour = 0
    return parsed_time.replace(hour=hour).strftime("%H:%M")


def _interview_time_form_values(value):
    normalized_time = _normalize_interview_time(value)
    if normalized_time:
        parsed_time = datetime.strptime(normalized_time, "%H:%M")
        return {
            "interview_hour": parsed_time.strftime("%I"),
            "interview_minute": parsed_time.strftime("%M"),
            "interview_period": parsed_time.strftime("%p"),
            "interview_time_24": normalized_time,
        }
    return {
        "interview_hour": "09",
        "interview_minute": "00",
        "interview_period": "AM",
        "interview_time_24": "",
    }


def _submitted_interview_time(post_data, status):
    hour = post_data.get("interview_hour", "").strip()
    minute = post_data.get("interview_minute", "").strip()
    period = post_data.get("interview_period", "").strip().upper()
    legacy_time = post_data.get("interview_time", "").strip()

    if status == "Approved" and (
        "interview_hour" in post_data or "interview_minute" in post_data
    ):
        form_values = {
            "interview_hour": hour,
            "interview_minute": minute,
            "interview_period": period if period in {"AM", "PM"} else "AM",
            "interview_time_24": legacy_time,
        }
        try:
            if not (1 <= int(hour) <= 12 and 0 <= int(minute) <= 59):
                raise ValueError
            parsed_time = datetime.strptime(
                f"{hour}:{minute} {period}", "%I:%M %p"
            )
        except ValueError:
            return None, form_values
        return parsed_time.strftime("%H:%M"), form_values

    normalized_time = _normalize_interview_time(legacy_time)
    if normalized_time is None:
        form_values = _interview_time_form_values("")
        form_values.update({
            "interview_hour": hour,
            "interview_minute": minute,
            "interview_period": period or form_values["interview_period"],
            "interview_time_24": legacy_time,
        })
        return None, form_values
    form_values = _interview_time_form_values(normalized_time)
    form_values["interview_time_24"] = legacy_time
    return normalized_time, form_values


def _interview_schedule_error(interview_date, interview_time, required=False):
    if not interview_date or not interview_time:
        if required:
            return "Vui lòng nhập đầy đủ ngày và giờ hẹn."
        if interview_date or interview_time:
            return "Vui lòng nhập đầy đủ cả ngày và giờ hẹn."
        return ""

    try:
        scheduled_date = datetime.strptime(interview_date, "%Y-%m-%d").date()
        scheduled_time = datetime.strptime(interview_time, "%H:%M").time()
    except ValueError:
        return "Ngày hoặc giờ hẹn không hợp lệ."

    now = timezone.now()
    scheduled_at = datetime.combine(scheduled_date, scheduled_time)
    if timezone.is_aware(now):
        scheduled_at = timezone.make_aware(
            scheduled_at,
            timezone.get_current_timezone(),
        )
    if scheduled_at < now:
        return "Ngày và giờ hẹn không được ở trước thời điểm hiện tại."
    return ""


def _current_local_date():
    now = timezone.now()
    if timezone.is_aware(now):
        now = timezone.localtime(now)
    return now.date()


def _notification_application(notification):
    application = notification.application
    if application and application.job.recruiter_id == notification.recipient_id:
        return application

    if not notification.job_title:
        return None

    time_window = timedelta(hours=12)
    applications = list(
        Application.objects.filter(
            job__recruiter_id=notification.recipient_id,
            job__title=notification.job_title,
            applied_at__gte=notification.created_at - time_window,
            applied_at__lte=notification.created_at + time_window,
        )
        .select_related("job", "candidate__profile")
        .order_by("-applied_at")
    )
    if not applications:
        return None

    reported_name = notification.message.partition(" vừa nộp hồ sơ")[0].strip()
    matching_applications = [
        item
        for item in applications
        if reported_name
        in {
            item.candidate.display_name,
            item.candidate.get_full_name().strip(),
            item.candidate.username,
        }
    ]
    candidates = matching_applications or applications
    return min(
        candidates,
        key=lambda item: abs((item.applied_at - notification.created_at).total_seconds()),
    )


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
            candidate_name = request.user.display_name
            Notification.objects.create(
                recipient=job.recruiter,
                title="Ứng viên mới ứng tuyển",
                message=f"{candidate_name} vừa nộp hồ sơ ứng tuyển vào tin tuyển dụng này.",
                job_title=job.title,
                company_name=job.company_name,
                application=application,
            )
            return render(request, "jobs/apply_success.html", {"job": job})
    else:
        form = ApplicationForm()
    return render(request, "jobs/apply_form.html", {"job": job, "form": form})


@login_required
def job_applications(request, pk):
    job = get_object_or_404(Job, pk=pk, recruiter=request.user)
    applications = job.applications.select_related(
        "candidate__profile"
    ).order_by("-applied_at")
    application_id = request.GET.get("application_id", "").strip()
    selected_application_id = None
    if application_id.isdigit() and applications.filter(pk=application_id).exists():
        selected_application_id = int(application_id)
    return render(
        request,
        "jobs/job_applications.html",
        {
            "job": job,
            "applications": applications,
            "selected_application_id": selected_application_id,
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
    time_form_values = _interview_time_form_values(parsed.get("time", ""))
    interview_note = parsed.get("note", "")
    company_profile = getattr(request.user, "company_profile", None)
    interview_location = (
        company_profile.address.strip()
        if company_profile and company_profile.address
        else ""
    )

    if request.method == "POST":
        action = request.POST.get("action", "update_status")
        status = request.POST.get("status")
        interview_date = request.POST.get("interview_date", "").strip()
        time_status = application.status if action == "update_schedule" else status
        interview_time, time_form_values = _submitted_interview_time(
            request.POST, time_status
        )
        interview_note = request.POST.get("interview_note", "").strip()

        if interview_time is None:
            return render(
                request,
                "jobs/update_application.html",
                {
                    "application": application,
                    "interview_date": interview_date,
                    **time_form_values,
                    "min_interview_date": _current_local_date().isoformat(),
                    "hour_choices": INTERVIEW_HOUR_CHOICES,
                    "minute_choices": INTERVIEW_MINUTE_CHOICES,
                    "interview_location": interview_location,
                    "interview_note": interview_note,
                    "selected_status": (
                        application.status if action == "update_schedule" else status
                    ),
                    "time_status": time_status,
                    "schedule_error": (
                        "Vui lòng chọn giờ 12 tiếng và AM/PM."
                        if time_status == "Approved"
                        else "Giờ không hợp lệ. Vui lòng chọn giờ theo định dạng 24 tiếng."
                    ),
                },
            )

        if action == "update_schedule":
            schedule_error = _interview_schedule_error(
                interview_date, interview_time, required=True
            )
            if schedule_error:
                return render(
                    request,
                    "jobs/update_application.html",
                    {
                        "application": application,
                        "interview_date": interview_date,
                        **time_form_values,
                        "min_interview_date": _current_local_date().isoformat(),
                        "hour_choices": INTERVIEW_HOUR_CHOICES,
                        "minute_choices": INTERVIEW_MINUTE_CHOICES,
                        "interview_location": interview_location,
                        "interview_note": interview_note,
                        "selected_status": application.status,
                        "time_status": application.status,
                        "schedule_error": schedule_error,
                    },
                )

            with transaction.atomic():
                application = Application.objects.select_for_update().get(
                    pk=application.pk
                )
                current_details = parse_interview_details(
                    application.interview_details
                )
                updated_interview_details = build_interview_details(
                    interview_date,
                    interview_time,
                    interview_location or current_details.get("location", ""),
                    current_details.get("note", ""),
                )
                schedule_changed = (
                    (application.interview_details or "") != updated_interview_details
                )
                if schedule_changed:
                    application.interview_details = updated_interview_details
                    application.reminder_sent = False
                    application.save(
                        update_fields=[
                            "interview_details",
                            "reminder_sent",
                            "updated_at",
                        ]
                    )
                    JobChatMessage.objects.create(
                        job=application.job,
                        sender=request.user,
                        receiver=application.candidate,
                        sender_name=request.user.display_name,
                        receiver_name=application.candidate.username,
                        message=(
                            f"Lịch hẹn cho hồ sơ ứng tuyển vị trí "
                            f"'{application.job.title}' đã được nhà tuyển dụng cập nhật.\n"
                            f"Lịch hẹn:\n{application.interview_details}"
                        ),
                        is_read=False,
                        is_application_update=True,
                        created_at=timezone.now(),
                    )

            if schedule_changed:
                try:
                    send_application_status_email(application)
                except Exception as error:
                    messages.warning(
                        request,
                        f"Đã lưu lịch hẹn nhưng không gửi được email cho ứng viên: {error}",
                    )
                else:
                    messages.success(
                        request,
                        "Đã cập nhật lịch hẹn; trạng thái hồ sơ được giữ nguyên.",
                    )
            else:
                messages.success(request, "Lịch hẹn không thay đổi.")
            return redirect("job_applications", pk=application.job.pk)

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
                    **time_form_values,
                    "min_interview_date": _current_local_date().isoformat(),
                    "hour_choices": INTERVIEW_HOUR_CHOICES,
                    "minute_choices": INTERVIEW_MINUTE_CHOICES,
                    "interview_location": interview_location,
                    "interview_note": interview_note,
                    "selected_status": status,
                    "time_status": status,
                    "status_error": "Cần nhập ngày và giờ hẹn trước khi duyệt phỏng vấn.",
                },
            )
        schedule_error = _interview_schedule_error(
            interview_date,
            interview_time,
            required=status == "Approved",
        )
        if schedule_error:
            return render(
                request,
                "jobs/update_application.html",
                {
                    "application": application,
                    "interview_date": interview_date,
                    **time_form_values,
                    "min_interview_date": _current_local_date().isoformat(),
                    "hour_choices": INTERVIEW_HOUR_CHOICES,
                    "minute_choices": INTERVIEW_MINUTE_CHOICES,
                    "interview_location": interview_location,
                    "interview_note": interview_note,
                    "selected_status": status,
                    "time_status": status,
                    "schedule_error": schedule_error,
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
                            **time_form_values,
                            "min_interview_date": _current_local_date().isoformat(),
                            "hour_choices": INTERVIEW_HOUR_CHOICES,
                            "minute_choices": INTERVIEW_MINUTE_CHOICES,
                            "interview_location": interview_location,
                            "interview_note": interview_note,
                            "selected_status": status,
                            "status_error": (
                                f'Tin này đã đủ chỉ tiêu nhận {job.max_hires} người. '
                                'Hãy tăng chỉ tiêu hoặc chuyển một hồ sơ khác khỏi '
                                'trạng thái thử việc/đã nhận.'
                            ),
                        },
                    )

            application.status = status
            updated_interview_details = build_interview_details(
                interview_date,
                interview_time,
                interview_location,
                interview_note,
            )
            previous_interview_details = application.interview_details or ""
            status_changed = previous_status != status
            schedule_changed = previous_interview_details != updated_interview_details
            application.interview_details = updated_interview_details
            if status_changed or schedule_changed:
                application.reminder_sent = False
            application.save()

            status_display = application.get_status_display()
            if status_changed or schedule_changed:
                schedule_label = (
                    "Lịch phỏng vấn"
                    if status == "Approved"
                    else "Lịch bắt đầu thử việc/đi làm"
                )
                if status_changed:
                    msg_content = (
                        f"Hồ sơ ứng tuyển vị trí '{job.title}' của bạn đã được cập nhật "
                        f"trạng thái mới: {status_display}."
                    )
                else:
                    msg_content = (
                        f"Lịch hẹn cho hồ sơ ứng tuyển vị trí '{job.title}' "
                        "đã được nhà tuyển dụng cập nhật."
                    )
                if application.interview_details:
                    msg_content += (
                        f"\n{schedule_label}:\n{application.interview_details}"
                    )

                # Tạo thông báo riêng biệt cho nút chuông và email với thời gian chuẩn xác từng giây
                JobChatMessage.objects.create(
                    job=job,
                    sender=request.user,
                    receiver=application.candidate,
                    sender_name=request.user.display_name,
                    receiver_name=application.candidate.username,
                    message=msg_content,
                    is_read=False,
                    is_application_update=True,
                    created_at=timezone.now(),  # Đồng bộ thời gian chính xác tuyệt đối
                )

        email_error = None
        if status_changed or schedule_changed:
            try:
                send_application_status_email(application)
            except Exception as error:
                email_error = error

        # Thông báo phản hồi giao diện
        if email_error:
            messages.warning(
                request,
                f"Đã lưu thay đổi nhưng không gửi được email cho ứng viên: {email_error}",
            )
        elif status == "Approved" and interview_date and (status_changed or schedule_changed):
            messages.success(request, "Đã lưu trạng thái phê duyệt và lịch hẹn phỏng vấn thành công.")
        elif status == "Rejected":
            messages.info(request, "Đã cập nhật trạng thái từ chối và gửi email thông báo cho ứng viên.")
        elif not status_changed and not schedule_changed:
            messages.success(request, "Thông tin hồ sơ đã được lưu.")
        elif schedule_changed:
            messages.success(request, "Đã cập nhật lịch hẹn và gửi email thông báo cho ứng viên.")
        else:
            messages.success(request, "Đã cập nhật trạng thái và gửi email thông báo cho ứng viên.")

        return redirect("job_applications", pk=application.job.pk)

    return render(
        request,
        "jobs/update_application.html",
        {
            "application": application,
            "interview_date": interview_date,
            **time_form_values,
            "min_interview_date": _current_local_date().isoformat(),
            "hour_choices": INTERVIEW_HOUR_CHOICES,
            "minute_choices": INTERVIEW_MINUTE_CHOICES,
            "interview_location": interview_location,
            "interview_note": interview_note,
            "selected_status": application.status,
            "time_status": application.status,
        },
    )

@login_required
def candidate_applications(request):
    """Trang 'Việc làm đã ứng tuyển' chỉ hiển thị danh sách ứng tuyển thực tế, không có banner thông báo rườm rà"""
    applications = Application.objects.filter(candidate=request.user).order_by("-applied_at")
    notifications = JobChatMessage.objects.filter(
        receiver=request.user,
        is_application_update=True,
    ).select_related("job").order_by("-created_at")
    notifications.update(is_read=True)

    for app in applications:
        if app.needs_interview_reminder and not app.reminder_sent:
            try:
                send_interview_reminder_email(app)
            except Exception as error:
                messages.warning(
                    request,
                    f"Không gửi được email nhắc lịch phỏng vấn: {error}",
                )

    return render(
        request,
        "jobs/candidate_applications.html",
        {
            "applications": applications,
            "notifications": list(notifications),
        },
    )


@login_required
def get_notifications_ajax(request):
    """Return application notifications for the signed-in user."""
    if getattr(request.user, "is_recruiter", False):
        notifications = Notification.objects.filter(
            recipient=request.user
        ).select_related("application__job").order_by("-created_at")
        data = []
        for notification in notifications:
            application = _notification_application(notification)
            action_url = None
            if application:
                action_url = (
                    reverse("job_applications", args=[application.job_id])
                    + "?"
                    + urlencode({"application_id": application.pk})
                )
            data.append({
                "id": notification.pk,
                "type": "recruiter",
                "title": notification.title,
                "job_title": notification.job_title,
                "company_name": notification.company_name,
                "message": notification.message,
                "created_at": notification.created_at.strftime("%H:%M %d/%m/%Y"),
                "is_read": notification.is_read,
                "action_url": action_url,
            })
    elif getattr(request.user, "is_candidate", False):
        notifications = JobChatMessage.objects.filter(
            receiver=request.user,
            is_application_update=True,
        ).select_related("job").order_by("-created_at")
        data = [
            {
                "id": notification.pk,
                "type": "candidate",
                "title": "Cập nhật hồ sơ ứng tuyển",
                "job_title": notification.job.title,
                "company_name": notification.job.company_name,
                "message": notification.message,
                "created_at": notification.created_at.strftime("%H:%M %d/%m/%Y"),
                "is_read": notification.is_read,
            }
            for notification in notifications
        ]
    else:
        return JsonResponse({"notifications": [], "unread_count": 0})

    return JsonResponse({
        "notifications": data,
        "unread_count": notifications.filter(is_read=False).count(),
    })


@login_required
def mark_notification_read_ajax(request):
    if request.method != "POST":
        return JsonResponse({"status": "error"}, status=405)

    notif_id = request.POST.get("notif_id")
    if not notif_id:
        return JsonResponse({"status": "error"}, status=400)

    if getattr(request.user, "is_recruiter", False):
        updated = Notification.objects.filter(
            pk=notif_id, recipient=request.user
        ).update(is_read=True)
    else:
        updated = JobChatMessage.objects.filter(
            pk=notif_id,
            receiver=request.user,
            is_application_update=True,
        ).update(is_read=True)
    return JsonResponse({"status": "success" if updated else "not_found"},
                        status=200 if updated else 404)


@login_required
def delete_notification_ajax(request):
    if request.method != "POST":
        return JsonResponse({"status": "error"}, status=405)

    notif_id = request.POST.get("notif_id")
    if not notif_id:
        return JsonResponse({"status": "error"}, status=400)

    if getattr(request.user, "is_recruiter", False):
        deleted, _ = Notification.objects.filter(
            pk=notif_id, recipient=request.user
        ).delete()
    else:
        deleted, _ = JobChatMessage.objects.filter(
            pk=notif_id,
            receiver=request.user,
            is_application_update=True,
        ).delete()
    return JsonResponse({"status": "success" if deleted else "not_found"},
                        status=200 if deleted else 404)


@login_required
def mark_all_notifications_read_ajax(request):
    if request.method != "POST":
        return JsonResponse({"status": "error"}, status=405)

    if getattr(request.user, "is_recruiter", False):
        notifications = Notification.objects.filter(recipient=request.user)
    else:
        notifications = JobChatMessage.objects.filter(
            receiver=request.user, is_application_update=True
        )
    notifications.filter(is_read=False).update(is_read=True)
    return JsonResponse({"status": "success"})


@login_required
def delete_all_notifications_ajax(request):
    if request.method != "POST":
        return JsonResponse({"status": "error"}, status=405)

    if getattr(request.user, "is_recruiter", False):
        Notification.objects.filter(recipient=request.user).delete()
    else:
        JobChatMessage.objects.filter(
            receiver=request.user, is_application_update=True
        ).delete()
    return JsonResponse({"status": "success"})