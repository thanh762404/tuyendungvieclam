from django.core.management.base import BaseCommand, CommandError
from jobs.models import Application
from jobs.services import send_interview_reminder_email


class Command(BaseCommand):
    help = "Gửi email nhắc các ứng viên có lịch phỏng vấn trong vòng 24 giờ tới"

    def handle(self, *args, **kwargs):
        applications = Application.objects.filter(
            status="Approved",
            reminder_sent=False,
        ).select_related("candidate", "job")
        sent_count = 0
        failure_count = 0

        for app in applications:
            try:
                if send_interview_reminder_email(app):
                    sent_count += 1
                    self.stdout.write(
                        f"Đã gửi email nhắc lịch cho hồ sơ #{app.pk}."
                    )
            except Exception as error:
                failure_count += 1
                self.stderr.write(
                    f"Không gửi được email nhắc lịch cho hồ sơ "
                    f"#{app.pk}: {error}"
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Hoàn tất: gửi {sent_count} email nhắc lịch; "
                f"lỗi {failure_count} email."
            )
        )
        if failure_count:
            self.stderr.write(
                "Các email lỗi sẽ được thử lại ở lần chạy định kỳ tiếp theo."
            )
            raise CommandError(
                f"Có {failure_count} email nhắc lịch chưa gửi được."
            )