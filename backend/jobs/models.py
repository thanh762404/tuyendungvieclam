from datetime import datetime, timedelta

from accounts.models import User
from django.db import models
from django.utils import timezone


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

    def __str__(self):
        return self.company_name


# ==========================================
# 4 MODEL MỚI PHỤC VỤ CHO GÓI CƯỚC & THANH TOÁN
# ==========================================

class SubscriptionPackage(models.Model):
    """Gói cước đăng tin do Admin thiết lập (VD: Gói 7 ngày, 30 ngày...)"""
    name = models.CharField(max_length=100, verbose_name="Tên gói cước")
    duration_days = models.IntegerField(verbose_name="Thời hạn (số ngày)")
    post_limit = models.IntegerField(default=10, verbose_name="Số lượng tin được phép đăng") # Đã thêm theo yêu cầu
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
  package_expires_at = models.DateTimeField(
      blank=True, null=True, verbose_name="Ngày hết hạn gói cước"
  )

  # 👉 THÊM CỘT LƯU TÊN NHÀ TUYỂN DỤNG TRỰC TIẾP
  recruiter_name = models.CharField(
      max_length=150, blank=True, null=True, verbose_name="Tên nhà tuyển dụng"
  )

  def save(self, *args, **kwargs):
    # Tự động đồng bộ tên username vào cột recruiter_name trước khi lưu
    if self.user:
      self.recruiter_name = self.user.username
    super().save(*args, **kwargs)

  @property
  def is_package_active(self):
    """Kiểm tra xem gói cước hiện tại còn hạn hay không và còn tin đăng không"""
    if self.active_package and self.package_expires_at:
      return (
          self.package_expires_at > timezone.now()
          and self.posts_remaining > 0
      )
    return False

  def __str__(self):
    return (
        f"Tài khoản NTD: {self.recruiter_name or self.user.username} (Tin miễn"
        f" phí: {self.free_posts_left} | Tin gói: {self.posts_remaining})"
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
  amount = models.DecimalField(
      max_digits=10, decimal_places=0, verbose_name="Số tiền thanh toán"
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

  # 👉 THÊM 2 CỘT MỚI ĐỂ LƯU TRỰC TIẾP TÊN
  recruiter_name = models.CharField(
      max_length=150, blank=True, null=True, verbose_name="Tên nhà tuyển dụng"
  )
  package_name = models.CharField(
      max_length=150, blank=True, null=True, verbose_name="Tên gói cước"
  )

  def save(self, *args, **kwargs):
    # Tự động gán tên nhà tuyển dụng và tên gói cước trước khi lưu vào CSDL
    if self.recruiter:
      self.recruiter_name = self.recruiter.username  # Hoặc lấy .get_full_name() nếu có
    if self.package:
      self.package_name = self.package.name  # Giả sử model gói cước có trường `name`

    super().save(*args, **kwargs)

  def __str__(self):
    return (
        f"GD #{self.id} - {self.recruiter_name or self.recruiter.username} -"
        f" {self.get_status_display()}"
    )


# ==========================================
# CÁC MODEL CŨ CỦA BẠN (GIỮ NGUYÊN)
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

    # BỔ SUNG 2 TRƯỜNG NÀY ĐỂ LỌC TÌM KIẾM
    major_required = models.CharField(max_length=255, blank=True, null=True, verbose_name="Ngành yêu cầu")
    skills_required = models.TextField(blank=True, null=True, verbose_name="Kỹ năng yêu cầu")

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
    status = models.CharField(
        max_length=20,
        choices=[
            ("Pending", "Chờ duyệt"),
            ("Approved", "Đã duyệt"),
            ("Rejected", "Từ chối"),
        ],
        default="Pending",
        verbose_name="Trạng thái duyệt",
    )

    @property
    def company_obj(self):
        """Lấy profile công ty của nhà tuyển dụng đăng bài này"""
        try:
            return self.recruiter.company_profile
        except CompanyProfile.DoesNotExist:
            return None

    @property
    def get_company_name(self):
        """Ưu tiên lấy tên công ty từ Profile, nếu không có thì lấy trường company_name"""
        profile = self.company_obj
        if profile and profile.company_name:
            return profile.company_name
        return self.company_name

    @property
    def company_logo(self):
        """Lấy file logo riêng của nhà tuyển dụng đăng bài để tránh bị trùng lặp"""
        profile = self.company_obj
        if profile and profile.company_logo:
            return profile.company_logo
        return None

    def save(self, *args, **kwargs):
        # Tự động đồng bộ tên công ty từ CompanyProfile sang Job nếu chưa điền
        if not self.company_name:
            profile = self.company_obj
            if profile:
                self.company_name = profile.company_name
        super().save(*args, **kwargs)

    @property
    def is_expired_status(self):
        """Kiểm tra xem tin tuyển dụng đã quá hạn hay chưa"""
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False

    @property
    def is_urgent_status(self):
        """Sắp hết hạn: Còn dưới 3 ngày nữa là hết hạn và chưa thực sự hết hạn"""
        if self.expires_at and not self.is_expired_status:
            time_left = self.expires_at - timezone.now()
            return 0 < time_left.total_seconds() <= (3 * 24 * 60 * 60)
        return False

    @property
    def is_new_status(self):
        """Tin được coi là 'Mới' nếu được đăng trong vòng 3 ngày gần đây"""
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
            ("Rejected", "Từ chối"),
        ],
        default="Pending",
        verbose_name="Trạng thái",
    )
    updated_at = models.DateTimeField(auto_now=True)

    interview_details = models.TextField(
        blank=True,
        null=True,
        verbose_name="Lịch hẹn và thông tin phỏng vấn trực tiếp",
    )
    applied_at = models.DateTimeField(auto_now_add=True, verbose_name="Ngày nộp")
    
    # Đánh dấu xem đã gửi email nhắc nhở dưới 24h chưa để tránh gửi lặp lại
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
    def interview_note(self):
        if not self.interview_details:
            return ""
        for line in self.interview_details.splitlines():
            if line.lower().startswith("nội dung:"):
                return line.split(":", 1)[1].strip()
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

        # Luôn luôn ép về dạng aware (có múi giờ) để không bao giờ bị lỗi so sánh
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
        
        # Đảm bảo cả hai cùng dạng aware hoặc naive trước khi so sánh
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


class JobChatMessage(models.Model):
    """Bảng lưu trữ tin nhắn chat trực tiếp giữa ứng viên và nhà tuyển dụng theo từng bài đăng tuyển dụng"""

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