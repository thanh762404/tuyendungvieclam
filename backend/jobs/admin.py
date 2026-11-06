from django.contrib import admin
from .models import (
    Job, 
    Application, 
    JobChatMessage, 
    ContactMessage, 
    CompanyProfile,
    SubscriptionPackage,
    RecruiterAccount,
    PackageTransaction,
    QualifiedCandidate,
    SystemFeature,
)

@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'company_name',
        'recruiter_name',
        'location',
        'salary',
        'job_type',
        'created_at',
    )
    search_fields = ('title', 'company_name', 'recruiter_name', 'job_type')

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
    list_display = (
        'user',
        'free_posts_left',
        'active_package',
        'total_posts_purchased',
        'posts_remaining',
        'package_expires_at',
    )
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
        'package_posts_count',
    )

admin.site.register(ContactMessage)


@admin.register(QualifiedCandidate)
class QualifiedCandidateAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "candidate_name",
        "company_name",
        "job",
        "recruiter",
        "status",
        "qualified_at",
    )
    list_filter = ("status", "recruiter", "job", "qualified_at")
    search_fields = (
        "candidate__email",
        "candidate__username",
        "candidate__first_name",
        "candidate__last_name",
        "job__title",
        "job__company_name",
        "recruiter__email",
        "recruiter__username",
    )
    readonly_fields = (
        "application",
        "candidate",
        "job",
        "recruiter",
        "status",
        "qualified_at",
    )

    @admin.display(description="Ứng viên")
    def candidate_name(self, obj):
        return obj.candidate.display_name

    @admin.display(description="Công ty")
    def company_name(self, obj):
        return obj.job.get_company_name or obj.recruiter.display_name

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SystemFeature)
class SystemFeatureAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "actor", "storage_status", "related_tables")
    list_filter = ("actor", "storage_status")
    search_fields = ("code", "name", "actor", "related_tables", "notes")