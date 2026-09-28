from django.core.mail import send_mail
from django.conf import settings

def send_interview_reminder_email(application):
    if application.needs_interview_reminder:
        candidate_email = application.candidate.email # Hoặc lấy email của ứng viên tùy theo model User của bạn
        subject = f"[Nhắc nhở] Lịch phỏng vấn công việc: {application.job.title}"
        message = application.interview_reminder_message
        
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [candidate_email],
            fail_silently=False,
        )