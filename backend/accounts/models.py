from django.db import models
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    is_candidate = models.BooleanField(default=False)
    is_recruiter = models.BooleanField(default=False)
    recruiter_cv = models.FileField(
        upload_to='recruiter_cvs/',
        blank=True,
        null=True,
        verbose_name='CV xác minh nhà tuyển dụng',
    )


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone = models.CharField(max_length=15, blank=True, null=True)
    bio = models.TextField(
        blank=True,
        null=True,
        verbose_name="Giới thiệu bản thân"
    )

    # Kỹ năng ứng viên tự chọn khi đăng ký/chỉnh sửa hồ sơ
    skills = models.TextField(
        blank=True,
        null=True,
        verbose_name="Kỹ năng"
    )

    # Kỹ năng được hệ thống trích xuất từ CV
    cv_skills = models.TextField(
        blank=True,
        null=True,
        verbose_name="Kỹ năng trích xuất từ CV"
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

    # Tên tài khoản ứng viên
    candidate_name = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        verbose_name="Tên tài khoản ứng viên"
    )

    def save(self, *args, **kwargs):
        if self.user:
            self.candidate_name = self.user.username
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Hồ sơ của {self.candidate_name or self.user.username}"