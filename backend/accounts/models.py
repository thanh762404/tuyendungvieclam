from django.db import models
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    # Cho phép username không bắt buộc và dùng email làm định danh chính để đăng nhập
    username = models.CharField(max_length=150, blank=True, null=True)
    email = models.EmailField(unique=True, verbose_name='Email đăng nhập')
    
    is_candidate = models.BooleanField(default=False)
    is_recruiter = models.BooleanField(default=False)
    recruiter_cv = models.FileField(
        upload_to='recruiter_cvs/',
        blank=True,
        null=True,
        verbose_name='CV xác minh nhà tuyển dụng',
    )

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = [] # Không yêu cầu username khi tạo superuser

    @property
    def display_name(self):
        if self.is_recruiter:
            try:
                company_name = self.company_profile.company_name.strip()
            except ObjectDoesNotExist:
                company_name = ""
            if company_name == self.email:
                company_name = ""
            return company_name or "Nhà tuyển dụng"

        full_name = self.get_full_name().strip()
        if full_name:
            return full_name
        try:
            candidate_name = self.profile.candidate_name
        except ObjectDoesNotExist:
            candidate_name = ""
        return candidate_name or self.username or self.email


class Profile(models.Model):
    user = models.OneToOneField(User, on_dispose=models.CASCADE, related_name='profile') if hasattr(models, 'on_dispose') else models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone = models.CharField(max_length=15, blank=True, null=True)
    
    birth_date = models.DateField(blank=True, null=True, verbose_name="Ngày sinh")
    address = models.CharField(max_length=255, blank=True, null=True, verbose_name="Địa chỉ")

    bio = models.TextField(
        blank=True,
        null=True,
        verbose_name="Giới thiệu bản thân"
    )

    # Kỹ năng ứng viên tự chọn khi đăng ký/chỉnh sửa hồ sơ (giữ lại trường này)
    skills = models.TextField(
        blank=True,
        null=True,
        verbose_name="Kỹ năng"
    )

    major = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        verbose_name="Ngành đào tạo"
    )

    cv_file = models.FileField(
        upload_to='cvs/',
        blank=True,
        null=True,
        verbose_name="Tải lên CV (PDF/Word)"
    )

    avatar = models.ImageField(
        upload_to='avatars/',
        blank=True,
        null=True
    )

    candidate_name = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        verbose_name="Tên tài khoản ứng viên"
    )

    def save(self, *args, **kwargs):
        if self.user:
            full_name = f"{self.user.first_name} {self.user.last_name}".strip()
            self.candidate_name = full_name if full_name else self.user.email
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Hồ sơ của {self.candidate_name or self.user.email}"