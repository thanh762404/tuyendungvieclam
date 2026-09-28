from django.contrib import admin
from django.utils import timezone
from datetime import timedelta
from .models import (
    Job, 
    Application, 
    JobChatMessage, 
    ContactMessage, 
    CompanyProfile,
    SubscriptionPackage,
    RecruiterAccount,
    PackageTransaction
)

@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ('title', 'company_name', 'location', 'salary', 'job_type', 'created_at')
    search_fields = ('title', 'company_name', 'job_type')

@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ('job', 'candidate', 'status', 'applied_at')
    list_filter = ('status', 'applied_at')
    search_fields = ('job__title', 'candidate__username')

@admin.register(JobChatMessage)
class JobChatMessageAdmin(admin.ModelAdmin):
    list_display = ('job', 'sender_name', 'receiver_name', 'message', 'created_at', 'is_read')
    list_filter = ('is_read', 'created_at')
    search_fields = ('job__title', 'sender__username', 'receiver__username', 'message')

@admin.register(CompanyProfile)
class CompanyProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'company_name', 'phone', 'website')
    search_fields = ('company_name', 'user__username', 'phone')

@admin.register(SubscriptionPackage)
class SubscriptionPackageAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'duration_days', 'post_limit')
    search_fields = ('name',)

@admin.register(RecruiterAccount)
class RecruiterAccountAdmin(admin.ModelAdmin):
    list_display = ('user', 'free_posts_left', 'active_package', 'posts_remaining', 'package_expires_at')
    search_fields = ('user__username', 'user__email')
    list_filter = ('active_package',)

@admin.register(PackageTransaction)
class PackageTransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'recruiter', 'package', 'amount', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('recruiter__username', 'recruiter__email')
    actions = ['approve_transactions']

    def approve_transactions(self, request, queryset):
        """Hành động duyệt nhanh: Kích hoạt gói cước và tự động cộng số tin cho nhà tuyển dụng"""
        count = 0
        for tx in queryset.filter(status='pending'):
            tx.status = 'approved'
            tx.save()
            
            # Cập nhật hoặc tạo tài khoản NTD
            recruiter_acc, _ = RecruiterAccount.objects.get_or_create(user=tx.recruiter)
            recruiter_acc.active_package = tx.package
            recruiter_acc.posts_remaining += tx.package.post_limit
            
            # Tính thời hạn gói cước
            now = timezone.now()
            if recruiter_acc.package_expires_at and recruiter_acc.package_expires_at > now:
                recruiter_acc.package_expires_at += timedelta(days=tx.package.duration_days)
            else:
                recruiter_acc.package_expires_at = now + timedelta(days=tx.package.duration_days)
                
            recruiter_acc.save()
            count += 1
            
        self.message_user(request, f"Đã duyệt thành công {count} giao dịch và cộng tin vào tài khoản nhà tuyển dụng.")
    approve_transactions.short_description = "Duyệt giao dịch đã chọn (Cộng gói cước)"

admin.site.register(ContactMessage)