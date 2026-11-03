from django.core.mail import send_mail
from django.conf import settings


def _require_gmail_password():
    if not settings.EMAIL_HOST_PASSWORD:
        raise RuntimeError(
            "EMAIL_HOST_PASSWORD chưa được cấu hình. "
            "Hãy thêm Gmail App Password vào backend/.env rồi khởi động lại ứng dụng."
        )


def send_application_status_email(application):
    _require_gmail_password()
    candidate_email = application.candidate.email
    if not candidate_email:
        raise ValueError(
            f"Ứng viên {application.candidate_id} chưa có địa chỉ email."
        )

    status_display = application.get_status_display()
    company_name = application.job.get_company_name
    schedule_label = (
        "Lịch phỏng vấn"
        if application.status == "Approved"
        else "Lịch bắt đầu thử việc/đi làm"
    )
    message = (
        f"Xin chào {application.candidate.display_name},\n\n"
        f"Hồ sơ ứng tuyển vị trí '{application.job.title}' tại {company_name} "
        f"đã được cập nhật trạng thái: {status_display}."
    )
    if application.interview_details:
        message += f"\n\n{schedule_label}:\n{application.interview_details}"
    message += "\n\nTrân trọng,\nHệ thống tuyển dụng CTJob"

    sent_count = send_mail(
        f"[CTJob] Cập nhật hồ sơ ứng tuyển - {status_display}",
        message,
        settings.DEFAULT_FROM_EMAIL,
        [candidate_email],
        fail_silently=False,
    )
    if sent_count != 1:
        raise RuntimeError(
            f"Django không xác nhận đã gửi email cập nhật hồ sơ cho {candidate_email}."
        )
    return True


def send_interview_reminder_email(application):
    if application.reminder_sent or not application.needs_interview_reminder:
        return False

    _require_gmail_password()
    candidate_email = application.candidate.email
    if not candidate_email:
        raise ValueError(
            f"Ứng viên {application.candidate_id} chưa có địa chỉ email."
        )

    company_name = application.job.get_company_name
    subject = (
        f"[CTJob] Nhắc lịch phỏng vấn - {application.job.title} "
        f"tại {company_name}"
    )
    message = (
        f"Xin chào {application.candidate.display_name},\n\n"
        f"{application.interview_reminder_message}\n\n"
        f"Chi tiết lịch hẹn:\n{application.interview_details}\n\n"
        f"Vui lòng sắp xếp thời gian có mặt đúng giờ.\n\n"
        f"Trân trọng,\n{company_name}\n"
        "Hệ thống tuyển dụng CTJob"
    )

    sent_count = send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [candidate_email],
        fail_silently=False,
    )
    if sent_count != 1:
        raise RuntimeError(
            f"Django không xác nhận đã gửi email nhắc lịch cho {candidate_email}."
        )

    application.reminder_sent = True
    application.save(update_fields=["reminder_sent"])
    return True