from datetime import datetime, timedelta
import uuid

from accounts.models import User
from django.db import models
from django.utils import timezone


HIRING_CAPACITY_STATUSES = ('InterviewPassed', 'Trial', 'Hired')
HIRING_PIPELINE_STATUSES = HIRING_CAPACITY_STATUSES


def generate_package_payment_code():
    return f"CTJ{uuid.uuid4().hex[:12].upper()}"


class CompanyProfile(models.Model):
    """Bảng thông tin nhà tuyển dụng/công ty để quản lý logo và thương hiệu riêng biệt cho từng tài khoản"""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="company_profile",
        limit_choices_to={"is_recruiter": True},
        verbose_name="Tài khoản nhà tuyển dụng",
    )
    company_name = models.CharField(max_length=255, verbose_name="Tên công ty")
    phone = models.CharField(
        max_length=15, blank=True, null=True, verbose_name="Số điện thoại liên hệ"
    )
    company_logo = models.ImageField(
        upload_to="company_logos/",
        blank=True,
        null=True,
        verbose_name="Logo công ty",
    )
    address = models.CharField(
        max_length=255, blank=True, null=True, verbose_name="Địa chỉ công ty"
    )
    website = models.URLField(
        blank=True, null=True, verbose_name="Website công ty"
    )
    description = models.TextField(
        blank=True, null=True, verbose_name="Giới thiệu công ty"
    )
    is_approved = models.BooleanField(default=False, verbose_name="Đã được Admin duyệt")
    approved_at = models.DateTimeField(blank=True, null=True, verbose_name="Thời gian Admin duyệt")

    def __str__(self):
        return self.company_name


# ==========================================
# 4 MODEL PHỤC VỤ CHO GÓI CƯỚC & THANH TOÁN
# ==========================================

class SubscriptionPackage(models.Model):
    """Gói cước đăng tin do Admin thiết lập (VD: Gói 7 ngày, 30 ngày...)"""
    name = models.CharField(max_length=100, verbose_name="Tên gói cước")
    duration_days = models.IntegerField(verbose_name="Thời hạn (số ngày)")
    post_limit = models.IntegerField(default=10, verbose_name="Số lượng tin được phép đăng")
    price = models.DecimalField(max_digits=10, decimal_places=0, verbose_name="Giá tiền (VNĐ)")
    description = models.TextField(blank=True, null=True, verbose_name="Mô tả quyền lợi gói")

    def __str__(self):
        return f"{self.name} - {self.price:,.0f} VNĐ ({self.duration_days} ngày - {self.post_limit} tin)"


class RecruiterAccount(models.Model):
    """Quản lý số lượng tin miễn phí còn lại và gói cước hiện tại của Nhà tuyển dụng"""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="recruiter_account",
        limit_choices_to={"is_recruiter": True},
        verbose_name="Nhà tuyển dụng",
    )
    free_posts_left = models.IntegerField(
        default=1, verbose_name="Số tin miễn phí còn lại"
    )
    active_package = models.ForeignKey(
        SubscriptionPackage,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name="Gói cước đang hoạt động",
    )
    posts_remaining = models.IntegerField(
        default=0, verbose_name="Số tin còn lại trong gói"
    )
    
    # Cột lưu số tin còn lại thực tế có thể sử dụng (tương thích phpMyAdmin)
    actual_usable_posts = models.IntegerField(
        default=0, verbose_name="Số lượng tin thực tế khả dụng"
    )

    total_posts_purchased = models.PositiveIntegerField(
        default=0, verbose_name="Tổng số lượt đăng đã mua"
    )
    package_expires_at = models.DateTimeField(
        blank=True, null=True, verbose_name="Ngày hết hạn gói cước"
    )
    package_started_at = models.DateTimeField(
        blank=True, null=True, verbose_name="Ngày bắt đầu gói cước"
    )

    recruiter_name = models.CharField(
        max_length=150, blank=True, null=True, verbose_name="Tên nhà tuyển dụng"
    )

    def update_usable_posts(self):
        """
        Tính toán chuẩn xác: 
        - Tổng tin khả dụng = Tổng số tin từ các giao dịch còn hạn.
        - Ngày hết hạn (package_expires_at) = Lấy ngày hết hạn của GÓI MỚI NHẤT VỪA MUA 
          (hoặc tính từ thời điểm mua gần nhất cộng dồn số ngày tương ứng).
        """
        now = timezone.now()
        approved_txs = PackageTransaction.objects.filter(
            recruiter=self.user,
            status="approved"
        ).select_related("package").order_by("-created_at") # Sắp xếp mới nhất lên đầu

        valid_posts = 0
        latest_expiry = None

        for tx in approved_txs:
            start_time = tx.verified_at or tx.created_at
            duration = tx.package.duration_days if tx.package else 0
            expiry_time = start_time + timedelta(days=duration)

            # Nếu giao dịch này còn hạn
            if expiry_time > now:
                valid_posts += tx.package_posts_count
                # Lấy mốc hết hạn của giao dịch mới nhất làm mốc hiển thị chính cho tài khoản
                if not latest_expiry:
                    latest_expiry = expiry_time

        # Nếu không còn giao dịch nào hạn thì reset về None và 0 tin
        if valid_posts == 0:
            self.package_expires_at = None
            self.actual_usable_posts = 0
            self.posts_remaining = 0
        else:
            self.package_expires_at = latest_expiry
            self.actual_usable_posts = min(self.posts_remaining, valid_posts)

        super().save(update_fields=["package_expires_at", "actual_usable_posts", "posts_remaining"])

    def save(self, *args, **kwargs):
        if self.user:
            self.recruiter_name = self.user.username
            
        now = timezone.now()
        if self.package_expires_at and self.package_expires_at > now:
            self.actual_usable_posts = max(0, self.posts_remaining)
        elif not self.package_expires_at:
            self.actual_usable_posts = max(0, self.posts_remaining)
        else:
            self.actual_usable_posts = 0
            
        super().save(*args, **kwargs)

    @property
    def is_package_active(self):
        if self.active_package and self.package_expires_at:
            return (
                self.package_expires_at > timezone.now()
                and self.actual_usable_posts > 0
            )
        return False

    def __str__(self):
        return (
            f"Tài khoản NTD: {self.recruiter_name or self.user.username} (Tin khả dụng: {self.actual_usable_posts})"
        )
class PackageTransaction(models.Model):
    """Lịch sử giao dịch chuyển khoản mua gói cước của Nhà tuyển dụng (Để Admin quản lý doanh thu)"""

    STATUS_CHOICES = (
        ("pending", "Chờ xác nhận thanh toán"),
        ("approved", "Đã thanh toán / Kích hoạt"),
        ("rejected", "Từ chối"),
    )

    recruiter = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={"is_recruiter": True},
        verbose_name="Nhà tuyển dụng",
    )
    package = models.ForeignKey(
        SubscriptionPackage, on_delete=models.CASCADE, verbose_name="Gói cước đăng ký"
    )
    package_posts_count = models.PositiveIntegerField(
        default=0, verbose_name="Số tin của gói tại thời điểm mua"
    )
    amount = models.DecimalField(
        max_digits=10, decimal_places=0, verbose_name="Số tiền thanh toán"
    )
    payment_code = models.CharField(
        max_length=15,
        unique=True,
        default=generate_package_payment_code,
        verbose_name="Mã nội dung thanh toán",
    )
    sepay_transaction_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        unique=True,
        verbose_name="Mã giao dịch SePay",
    )
    sepay_received_amount = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        blank=True,
        null=True,
        verbose_name="Số tiền nhận từ SePay",
    )
    verified_at = models.DateTimeField(
        blank=True, null=True, verbose_name="Thời gian xác nhận thanh toán"
    )
    proof_image = models.ImageField(
        upload_to="payment_proofs/",
        blank=True,
        null=True,
        verbose_name="Ảnh biên lai chuyển khoản",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
        verbose_name="Trạng thái giao dịch",
    )
    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name="Ngày tạo giao dịch"
    )

    recruiter_name = models.CharField(
        max_length=150, blank=True, null=True, verbose_name="Tên nhà tuyển dụng"
    )
    package_name = models.CharField(
        max_length=150, blank=True, null=True, verbose_name="Tên gói cước"
    )

    def save(self, *args, **kwargs):
        if self.recruiter:
            self.recruiter_name = self.recruiter.username
        if self.package:
            self.package_name = self.package.name
            if not self.pk and not self.package_posts_count:
                self.package_posts_count = self.package.post_limit

        super().save(*args, **kwargs)

    def __str__(self):
        return f"GD #{self.id} - {self.recruiter_name or self.recruiter.username} - {self.get_status_display()}"


# ==========================================
# CÁC MODEL KHÁC CỦA BẠN (GIỮ NGUYÊN)
# ==========================================

class Job(models.Model):
    title = models.CharField(max_length=255, verbose_name="Tiêu đề công việc")
    company_name = models.CharField(max_length=255, verbose_name="Tên công ty", blank=True)
    location = models.CharField(max_length=255, verbose_name="Địa điểm")
    salary = models.CharField(max_length=100, verbose_name="Mức lương")
    job_type = models.CharField(
        max_length=100,
        verbose_name="Hình thức (Toàn thời gian/Bán thời gian...)",
    )
    description = models.TextField(verbose_name="Mô tả công việc")
    requirements = models.TextField(verbose_name="Yêu cầu ứng viên")

    major_required = models.CharField(max_length=255, blank=True, null=True, verbose_name="Ngành yêu cầu")
    skills_required = models.TextField(blank=True, null=True, verbose_name="Kỹ năng yêu cầu")
    max_hires = models.PositiveIntegerField(
        default=5,
        verbose_name="Số người tối đa được nhận",
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Ngày đăng")

    expires_at = models.DateTimeField(
        blank=True, null=True, verbose_name="Hạn nộp hồ sơ"
    )

    recruiter = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={"is_recruiter": True},
        verbose_name="Nhà tuyển dụng",
    )
    recruiter_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Tên công ty nhà tuyển dụng",
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ("Pending", "Chờ duyệt"),
            ("Approved", "Đã duyệt"),
            ("Rejected", "Từ chối"),
        ],
        default="Approved",
        verbose_name="Trạng thái duyệt",
    )

    @property
    def company_obj(self):
        try:
            return self.recruiter.company_profile
        except CompanyProfile.DoesNotExist:
            return None

    @property
    def get_company_name(self):
        profile = self.company_obj
        if profile and profile.company_name:
            return profile.company_name
        return self.company_name

    @property
    def company_logo(self):
        profile = self.company_obj
        if profile and profile.company_logo:
            return profile.company_logo
        return None

    def save(self, *args, **kwargs):
        profile = self.company_obj
        if profile and profile.company_name:
            self.recruiter_name = profile.company_name.strip()
            if not self.company_name:
                self.company_name = profile.company_name
        else:
            self.recruiter_name = (
                self.company_name
                or self.recruiter.display_name
                or self.recruiter.email
            )
        if not self.company_name:
            self.company_name = self.recruiter_name
        super().save(*args, **kwargs)

    @property
    def is_expired_status(self):
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False

    @property
    def is_urgent_status(self):
        if self.expires_at and not self.is_expired_status:
            time_left = self.expires_at - timezone.now()
            return 0 < time_left.total_seconds() <= (3 * 24 * 60 * 60)
        return False

    @property
    def is_new_status(self):
        if self.created_at:
            return (timezone.now() - self.created_at).days <= 3
        return False

    def __str__(self):
        return self.title


class Application(models.Model):
    job = models.ForeignKey(
        Job,
        on_delete=models.CASCADE,
        related_name="applications",
        verbose_name="Tin tuyển dụng",
    )
    candidate = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={"is_candidate": True},
        verbose_name="Ứng viên",
    )
    cv_file = models.FileField(
        upload_to="applications_cvs/", verbose_name="CV ứng tuyển"
    )
    cover_letter = models.TextField(blank=True, verbose_name="Thư giới thiệu")

    status = models.CharField(
        max_length=50,
        choices=[
            ("Pending", "Đang chờ duyệt"),
            ("Approved", "Đã duyệt / Phỏng vấn"),
            ("InterviewPassed", "Đạt phỏng vấn"),
            ("Trial", "Đang thử việc"),
            ("Hired", "Đã nhận / Đang đi làm"),
            ("Rejected", "Từ chối"),
        ],
        default="Pending",
        verbose_name="Trạng thái",
    )
    updated_at = models.DateTimeField(auto_now=True)
    
    def get_status_display_vi(self):
        status_map = {
            'Pending': 'Đang chờ duyệt',
            'Approved': 'Đã duyệt / Phỏng vấn',
            'InterviewPassed': 'Đạt phỏng vấn',
            'Trial': 'Đang thử việc',
            'Hired': 'Đã nhận / Đang đi làm',
            'Rejected': 'Từ chối',
        }
        return status_map.get(self.status, self.status)
        
    interview_details = models.TextField(
        blank=True,
        null=True,
        verbose_name="Lịch hẹn và thông tin phỏng vấn trực tiếp",
    )
    applied_at = models.DateTimeField(auto_now_add=True, verbose_name="Ngày nộp")
    
    reminder_sent = models.BooleanField(
        default=False, 
        verbose_name="Đã gửi email nhắc nhở 24h"
    )

    @property
    def interview_date(self):
        if not self.interview_details:
            return ""
        for line in self.interview_details.splitlines():
            if line.lower().startswith("ngày:"):
                return line.split(":", 1)[1].strip()
        return ""

    @property
    def interview_time(self):
        if not self.interview_details:
            return ""
        for line in self.interview_details.splitlines():
            if line.lower().startswith("giờ:"):
                return line.split(":", 1)[1].strip()
        return ""

    @property
    def interview_location(self):
        if not self.interview_details:
            return ""
        for line in self.interview_details.splitlines():
            normalized_line = line.strip().lower()
            if normalized_line.startswith(("địa điểm:", "địa điểm hẹn:")):
                return line.split(":", 1)[1].strip()
        return ""

    @property
    def interview_note(self):
        if not self.interview_details:
            return ""

        lines = self.interview_details.splitlines()
        for index, line in enumerate(lines):
            normalized_line = line.strip().lower()
            if normalized_line.startswith(
                ("ghi chú:", "nội dung:", "nội dung/địa điểm:")
            ):
                note_lines = [line.split(":", 1)[1].strip(), *lines[index + 1 :]]
                return "\n".join(note_lines).strip()
        return ""

    @property
    def interview_datetime(self):
        if not self.interview_date:
            return None

        raw_datetime = str(self.interview_date).strip()
        if self.interview_time:
            time_str = str(self.interview_time).strip()
            raw_datetime = f"{raw_datetime} {time_str}"

        try:
            if self.interview_time:
                format_str = "%Y-%m-%d %H:%M:%S" if len(raw_datetime) > 16 else "%Y-%m-%d %H:%M"
                parsed = datetime.strptime(raw_datetime, format_str)
            else:
                parsed = datetime.strptime(raw_datetime[:10], "%Y-%m-%d")
        except ValueError:
            return None

        current_tz = timezone.get_current_timezone()
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, current_tz)
            
        return parsed

    @property
    def needs_interview_reminder(self):
        if self.status != "Approved":
            return False

        interview_dt = self.interview_datetime
        if not interview_dt:
            return False

        now = timezone.now()
        
        if timezone.is_naive(interview_dt) and not timezone.is_naive(now):
            interview_dt = timezone.make_aware(interview_dt, timezone.get_current_timezone())
        elif not timezone.is_naive(interview_dt) and timezone.is_naive(now):
            now = timezone.make_aware(now, timezone.get_current_timezone())

        if interview_dt <= now:
            return False

        return interview_dt - now <= timedelta(days=1)

    @property
    def interview_reminder_message(self):
        if not self.needs_interview_reminder:
            return ""

        if self.interview_datetime:
            return (
                f"Bạn có lịch phỏng vấn sắp tới trong vòng 24 giờ. "
                f"Vui lòng chuẩn bị và đến đúng thời gian: "
                f"{self.interview_date} {self.interview_time or ''}".strip()
            )
        return ""

    def __str__(self):
        return f"{self.candidate.username} - {self.job.title}"


class QualifiedCandidate(models.Model):
    application = models.OneToOneField(
        Application,
        on_delete=models.CASCADE,
        related_name="qualified_entry",
        verbose_name="Đơn ứng tuyển",
    )
    candidate = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="qualified_applications",
        limit_choices_to={"is_candidate": True},
        verbose_name="Ứng viên",
    )
    job = models.ForeignKey(
        Job,
        on_delete=models.CASCADE,
        related_name="qualified_candidates",
        verbose_name="Tin tuyển dụng",
    )
    recruiter = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="qualified_candidates",
        limit_choices_to={"is_recruiter": True},
        verbose_name="Nhà tuyển dụng",
    )
    candidate_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Tên ứng viên",
    )
    recruiter_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Tên nhà tuyển dụng",
    )
    company_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Tên công ty",
    )
    job_title = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Tên công việc",
    )
    status = models.CharField(
        max_length=50,
        choices=[
            (label, label)
            for status, label in Application._meta.get_field("status").choices
            if status in HIRING_PIPELINE_STATUSES
        ],
        verbose_name="Trạng thái đạt",
    )
    qualified_at = models.DateTimeField(
        default=timezone.now,
        verbose_name="Ngày vào danh sách ứng viên đạt",
    )

    class Meta:
        ordering = ("-qualified_at",)
        verbose_name = "Ứng viên đạt"
        verbose_name_plural = "Danh sách ứng viên đạt"

    def __str__(self):
        return f"{self.candidate} - {self.job}"


class JobChatMessage(models.Model):
    job = models.ForeignKey(
        Job,
        on_delete=models.CASCADE,
        related_name="chat_messages",
        verbose_name="Tin tuyển dụng",
    )
    sender = models.ForeignKey(
        User, on_delete=models.CASCADE, verbose_name="Người gửi"
    )
    receiver = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="received_chat_messages",
        verbose_name="Người nhận",
    )
    sender_name = models.CharField(
        max_length=255, blank=True, null=True, verbose_name="Tên người gửi"
    )
    receiver_name = models.CharField(
        max_length=255, blank=True, null=True, verbose_name="Tên người nhận"
    )
    message = models.TextField(verbose_name="Nội dung tin nhắn")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Thời gian gửi")
    is_read = models.BooleanField(default=False, verbose_name="Đã đọc")
    is_application_update = models.BooleanField(
        default=False, verbose_name="Thông báo cập nhật hồ sơ"
    )

    def __str__(self):
        return f"{self.sender.username} -> {self.receiver.username} ({self.job.title})"


class ContactMessage(models.Model):
    name = models.CharField(max_length=100, verbose_name="Họ và tên")
    email = models.EmailField(verbose_name="Email liên hệ")
    message = models.TextField(verbose_name="Nội dung")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Thời gian gửi")
    is_replied = models.BooleanField(default=False, verbose_name="Đã phản hồi")

    def __str__(self):
        return f"{self.name} - {self.email}"

class Notification(models.Model):
    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Người nhận thông báo",
    )
    title = models.CharField(max_length=255, verbose_name="Tiêu đề thông báo", default="Thông báo hệ thống")
    message = models.TextField(verbose_name="Nội dung chi tiết")
    is_read = models.BooleanField(default=False, verbose_name="Đã đọc")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Thời gian tạo")

    job_title = models.CharField(max_length=255, blank=True, null=True, verbose_name="Tên công việc liên quan")
    company_name = models.CharField(max_length=255, blank=True, null=True, verbose_name="Tên công ty")
    application = models.ForeignKey(
        Application,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="notifications",
        verbose_name="Đơn ứng tuyển liên quan",
    )

    def __str__(self):
        return f"Thông báo cho {self.recipient.username} - {self.title}"


class SystemFeature(models.Model):
    STORAGE_STATUS_CHOICES = (
        ("tables", "Có bảng dữ liệu"),
        ("derived", "Tổng hợp từ bảng hiện có"),
        ("static", "Nội dung tĩnh, không có bảng riêng"),
    )

    code = models.SlugField(max_length=100, unique=True, verbose_name="Mã chức năng")
    name = models.CharField(max_length=200, verbose_name="Tên chức năng")
    actor = models.CharField(max_length=50, verbose_name="Vai trò")
    storage_status = models.CharField(
        max_length=20,
        choices=STORAGE_STATUS_CHOICES,
        verbose_name="Trạng thái dữ liệu",
    )
    related_tables = models.TextField(
        blank=True,
        verbose_name="Bảng dữ liệu liên quan",
        help_text="Tên bảng MySQL, phân cách bằng dấu phẩy.",
    )
    notes = models.TextField(blank=True, verbose_name="Ghi chú")

    class Meta:
        ordering = ("actor", "code")
        verbose_name = "Chức năng hệ thống"
        verbose_name_plural = "Danh mục chức năng hệ thống"

    def __str__(self):
        return f"{self.name} ({self.actor})"