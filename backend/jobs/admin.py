from django.contrib import admin
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
    list_display = (
        'id',
        'recruiter',
        'package',
        'amount',
        'payment_code',
        'sepay_transaction_id',
        'status',
        'created_at',
    )
    list_filter = ('status', 'created_at')
    search_fields = (
        'recruiter__username',
        'recruiter__email',
        'payment_code',
        'sepay_transaction_id',
    )
    readonly_fields = (
        'recruiter',
        'package',
        'amount',
        'payment_code',
        'sepay_transaction_id',
        'verified_at',
        'proof_image',
        'status',
        'created_at',
        'recruiter_name',
        'package_name',
    )

admin.site.register(ContactMessage)