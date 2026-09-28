from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.core.mail import EmailMessage
from django.conf import settings
from jobs.models import Application

class Command(BaseCommand):
    help = 'Tự động quét lịch phỏng vấn trong vòng 24h tới và gửi email thông báo cho ứng viên'

    def handle(self, *args, **kwargs):
        now = timezone.now()
        target_time_limit = now + timedelta(hours=24)
        
        # Đổi mốc thời gian hiện tại ra timestamp (số thực)
        now_ts = now.timestamp()
        limit_ts = target_time_limit.timestamp()
        current_tz = timezone.get_current_timezone()

        # Lọc các đơn đã duyệt (Approved) và chưa gửi mail nhắc nhở
        applications = Application.objects.filter(status="Approved", reminder_sent=False)
        count = 0

        for app in applications:
            if not app.interview_date:
                continue

            raw_date = str(app.interview_date).strip()
            raw_time = str(app.interview_time).strip() if app.interview_time else "00:00"
            raw_datetime_str = f"{raw_date[:10]} {raw_time[:5]}"
            
            try:
                format_str = "%Y-%m-%d %H:%M"
                parsed_naive = datetime.strptime(raw_datetime_str, format_str)
                
                # Ép chuẩn aware rồi mới lấy timestamp để khớp tuyệt đối với now
                aware_dt = timezone.make_aware(parsed_naive, current_tz)
                dt_ts = aware_dt.timestamp()
            except ValueError:
                continue

            # So sánh bằng số học (timestamp) -> Chấp mọi loại lỗi naive/aware
            if now_ts <= dt_ts <= limit_ts:
                company_name = app.job.get_company_name
                candidate_email = app.candidate.email
                
                # Dùng trực tiếp email hệ thống làm from_email để tránh lỗi cú pháp
                dynamic_from_email = settings.DEFAULT_FROM_EMAIL
                
                # Đưa tên công ty vào tiêu đề hoặc nội dung cho rõ ràng, chuyên nghiệp
                subject = f"[Nhắc nhở] Lịch phỏng vấn vị trí {app.job.title} tại {company_name}"
                
                message = (
                    f"Xin chào {app.candidate.username},\n\n"
                    f"Hệ thống xin nhắc nhở bạn có lịch phỏng vấn sắp diễn ra trong vòng 24 giờ tới:\n\n"
                    f"{app.interview_details}\n\n"
                    f"Vui lòng sắp xếp thời gian có mặt đúng giờ nhé!\n\n"
                    f"Trân trọng,\n{company_name}"
                )

                try:
                    email_msg = EmailMessage(
                        subject=subject,
                        body=message,
                        from_email=dynamic_from_email,
                        to=[candidate_email],
                    )
                    email_msg.send()
                    
                    app.reminder_sent = True
                    app.save()
                    
                    count += 1
                    self.stdout.write(f"-> Đã gửi email nhắc nhở cho ứng viên: {app.candidate.username} (Công ty: {company_name})")
                except Exception as e:
                    self.stdout.write(f"-> Lỗi gửi mail cho {app.candidate.username}: {e}")

        self.stdout.write(self.style.SUCCESS(f"Hoàn tất! Đã gửi thành công {count} email nhắc nhở."))