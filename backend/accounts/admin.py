from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Profile

# Đăng ký User và Profile lên trang quản trị
class CustomUserAdmin(UserAdmin):
    model = User
    list_display = ['username', 'email', 'is_candidate', 'is_recruiter', 'is_staff']
    fieldsets = UserAdmin.fieldsets + (
        ('Thông tin phân quyền', {'fields': ('is_candidate', 'is_recruiter')}),
    )

admin.site.register(User, CustomUserAdmin)
admin.site.register(Profile)