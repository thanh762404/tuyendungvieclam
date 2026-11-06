from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import Q

from accounts.models import Profile, User

from .models import (
    Application,
    CompanyProfile,
    HIRING_PIPELINE_STATUSES,
    Job,
    QualifiedCandidate,
)

APPLICATION_STATUS_LABELS = dict(Application._meta.get_field("status").choices)


def _update_qualified_candidate_names(queryset):
    for qualified in queryset.select_related(
        "candidate",
        "candidate__profile",
        "recruiter__company_profile",
        "job",
    ):
        company_name = ""
        if hasattr(qualified.recruiter, "company_profile"):
            company_name = qualified.recruiter.company_profile.company_name.strip()
        if company_name == qualified.recruiter.email:
            company_name = ""

        qualified.candidate_name = qualified.candidate.display_name or "Ứng viên"
        qualified.recruiter_name = company_name or "Nhà tuyển dụng"
        qualified.company_name = (
            company_name or qualified.job.company_name or "Chưa cập nhật"
        )
        qualified.job_title = qualified.job.title
        qualified.save(
            update_fields=(
                "candidate_name",
                "recruiter_name",
                "company_name",
                "job_title",
            )
        )


@receiver(post_save, sender=Application)
def sync_qualified_candidate(sender, instance, **kwargs):
    if instance.status in HIRING_PIPELINE_STATUSES:
        QualifiedCandidate.objects.update_or_create(
            application=instance,
            defaults={
                "candidate": instance.candidate,
                "job": instance.job,
                "recruiter": instance.job.recruiter,
                "status": APPLICATION_STATUS_LABELS.get(
                    instance.status, instance.status
                ),
                "candidate_name": instance.candidate.display_name or "Ứng viên",
                "recruiter_name": instance.job.recruiter.display_name,
                "company_name": (
                    instance.job.recruiter.company_profile.company_name
                    if hasattr(instance.job.recruiter, "company_profile")
                    else instance.job.company_name or "Chưa cập nhật"
                ),
                "job_title": instance.job.title,
            },
        )
    else:
        QualifiedCandidate.objects.filter(application=instance).delete()


@receiver(post_save, sender=User)
def refresh_qualified_candidate_user_names(sender, instance, **kwargs):
    _update_qualified_candidate_names(
        QualifiedCandidate.objects.filter(
            Q(candidate=instance) | Q(recruiter=instance)
        )
    )


@receiver(post_save, sender=Profile)
def refresh_qualified_candidate_profile_name(sender, instance, **kwargs):
    _update_qualified_candidate_names(
        QualifiedCandidate.objects.filter(candidate=instance.user)
    )


@receiver(post_save, sender=CompanyProfile)
def refresh_qualified_candidate_company_name(sender, instance, **kwargs):
    company_name = instance.company_name.strip()
    Job.objects.filter(recruiter=instance.user).update(
        company_name=company_name,
        recruiter_name=company_name or instance.user.display_name,
    )
    _update_qualified_candidate_names(
        QualifiedCandidate.objects.filter(recruiter=instance.user)
    )
