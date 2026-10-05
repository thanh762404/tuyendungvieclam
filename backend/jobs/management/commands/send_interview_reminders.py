from django.core.management.base import BaseCommand
from jobs.models import Application
from jobs.services import send_interview_reminder_email

class Command(BaseCommand):
    help = 'Tự động quét lịch phỏng vấn trong vòng 24h tới và gửi email thông báo cho ứng viên'

    def handle(self, *args, **kwargs):
        applications = Application.objects.filter(
            status="Approved",
            reminder_sent=False,
        ).select_related("candidate", "job")
        count = 0

        for app in applications:
            try:
                if send_interview_reminder_email(app):
                    count += 1
                    self.stdout.write(
                        f"-> Đã gửi email nhắc lịch cho {app.candidate.username}."
                    )
            except Exception as error:
                self.stderr.write(
                    f"-> Không gửi được email nhắc lịch cho "
                    f"{app.candidate.username}: {error}"
                )

        self.stdout.write(self.style.SUCCESS(f"Hoàn tất! Đã gửi thành công {count} email nhắc nhở."))