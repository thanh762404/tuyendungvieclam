import re
from datetime import datetime
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from django.http import JsonResponse
from .models import Application, Job, JobChatMessage, Notification


def _normalize_match_text(value):
    return re.sub(r'\s+', ' ', (value or '').casefold().replace('–', '-').replace('—', '-')).strip()


def _normalize_skill(value):
    skill = _normalize_match_text(value)
    return {
        'node.js': 'nodejs',
        'react': 'reactjs',
        'react.js': 'reactjs',
    }.get(skill, skill)


def _contains_skill(text, skill):
    normalized_text = _normalize_match_text(text)
    normalized_skill = _normalize_skill(skill)
    aliases = {
        'nodejs': ('nodejs', 'node.js'),
        'reactjs': ('reactjs', 'react.js', 'react'),
    }.get(normalized_skill, (normalized_skill,))
    return any(
        re.search(rf'(?<!\w){re.escape(alias)}(?!\w)', normalized_text)
        for alias in aliases
    )


def _split_skills(value):
    return [skill.strip() for skill in re.split(r'[,;\n]+', value or '') if skill.strip()]


def _matched_skill_labels(skills, matched_skills):
    labels = []
    seen = set()
    for skill in skills:
        normalized_skill = _normalize_skill(skill)
        if normalized_skill in matched_skills and normalized_skill not in seen:
            labels.append(skill)
            seen.add(normalized_skill)
    return labels


from django.core.paginator import Paginator  # <--- Đảm bảo bạn có import dòng này ở đầu file views.py

def home_view(request):
    query = request.GET.get("q", "").strip()
    location = request.GET.get("location", "").strip()
    selected_skill_filter = request.GET.get("skills", "").strip()

    all_jobs = Job.objects.all().order_by("-created_at")

    if query:
        all_jobs = all_jobs.filter(
            Q(title__icontains=query) | Q(company_name__icontains=query)
        )

    if location:
        all_jobs = all_jobs.filter(location__icontains=location)

    active_jobs = []
    expired_jobs = []

    for job in all_jobs:
        if job.is_expired_status:
            expired_jobs.append(job)
        else:
            active_jobs.append(job)

    profile_skills = []
    candidate_major = ''
    has_cv_file = False

    if request.user.is_authenticated and getattr(request.user, "is_candidate", False):
        try:
            profile = request.user.profile
            candidate_major = _normalize_match_text(profile.major)
            profile_skills.extend(_split_skills(profile.skills))

            if profile.cv_file and profile.cv_file.name:
                has_cv_file = True
        except Exception:
            pass

    if selected_skill_filter:
        profile_skills = _split_skills(selected_skill_filter)

    suggested_jobs = []
    other_jobs = list(active_jobs)
    user_skills = list(dict.fromkeys(profile_skills))
    normalized_profile_skills = {
        _normalize_skill(skill) for skill in profile_skills if skill.strip()
    }
    
    if request.user.is_authenticated and getattr(request.user, "is_candidate", False):
        scored_suggestions = []
        temp_other_jobs = []
        for job in active_jobs:
            job_major = _normalize_match_text(job.major_required)
            major_matches = not job_major or (candidate_major and job_major == candidate_major)
            
            required_skills = {
                _normalize_skill(skill) for skill in _split_skills(job.skills_required)
            }
            
            if required_skills:
                matched_profile_skills = normalized_profile_skills & required_skills
                title_skills = {
                    skill for skill in required_skills
                    if _contains_skill(_normalize_match_text(job.title), skill)
                }
            else:
                job_title = _normalize_match_text(job.title)
                matched_profile_skills = {
                    skill for skill in normalized_profile_skills
                    if _contains_skill(job_title, skill)
                }
                title_skills = matched_profile_skills

            matched_skills = matched_profile_skills
            skill_coverage = len(matched_skills) / len(required_skills) if required_skills else bool(matched_skills)
            profile_title_match = bool(normalized_profile_skills & title_skills)
            profile_skill_match = bool(matched_profile_skills)
            has_candidate_skills = bool(normalized_profile_skills)
            
            major_only_match = not has_candidate_skills and candidate_major and job_major == candidate_major

            if not query and (major_matches or major_only_match) and (
                profile_skill_match or major_only_match
            ):
                job.recommendation_profile_skills = _matched_skill_labels(
                    profile_skills, matched_profile_skills
                )
                job.recommendation_cv_skills = []
                job.recommendation_score = round(skill_coverage * 100)
                scored_suggestions.append((
                    (
                        bool(matched_profile_skills),
                        len(matched_profile_skills),
                        skill_coverage,
                        0,
                        profile_title_match,
                        bool(job_major),
                    ),
                    job,
                ))
            else:
                temp_other_jobs.append(job)

        scored_suggestions.sort(key=lambda item: item[0], reverse=True)
        suggested_jobs = [job for _, job in scored_suggestions]
        other_jobs = temp_other_jobs

    if not request.user.is_authenticated or not getattr(request.user, "is_candidate", False):
        suggested_jobs = []
        other_jobs = active_jobs

    matching_jobs_count = len(suggested_jobs)
    total_active_jobs = len(active_jobs)
    total_other_jobs = len(other_jobs)
    total_expired_jobs = len(expired_jobs)

    # --- PHÂN TRANG CHO TẤT CẢ CÔNG VIỆC: MỖI TRANG HIỂN THỊ 9 CÔNG VIỆC ---
    paginator = Paginator(other_jobs, 9)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    unread_count = 0
    upcoming_interviews = None
    candidate_applications = []

    if request.user.is_authenticated and getattr(request.user, "is_candidate", False):
        candidate_applications = Application.objects.filter(
            candidate=request.user
        ).order_by('-updated_at')
        unread_count = JobChatMessage.objects.filter(
            receiver=request.user,
            is_application_update=True,
            is_read=False,
        ).count()
        
        now = timezone.now()
        for app in candidate_applications:
            if app.interview_details:
                text = app.interview_details
                try:
                    date_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', text)
                    time_match = re.search(r'(\d{2}):(\d{2})', text)
                    if date_match and time_match:
                        year, month, day = date_match.groups()
                        hour, minute = time_match.groups()
                        naive_dt = datetime(int(year), int(month), int(day), int(hour), int(minute))
                        interview_dt = timezone.make_aware(naive_dt, timezone.get_current_timezone())
                        total_secs = (interview_dt - now).total_seconds()
                        if -7200 <= total_secs <= 172800:
                            upcoming_interviews = app
                            break
                except Exception:
                    pass
    elif request.user.is_authenticated and getattr(request.user, "is_recruiter", False):
        unread_count = Notification.objects.filter(
            recipient=request.user, is_read=False
        ).count()

    return render(
        request,
        "home.html",
        {
            "jobs": active_jobs,
            "suggested_jobs": suggested_jobs,
            "other_jobs": page_obj,  # Truyền page_obj thay cho danh sách thô để template load phân trang
            "expired_jobs": expired_jobs,
            "query": query,
            "location": location,
            "user_skills": ", ".join(user_skills),
            "selected_skills": selected_skill_filter,
            "unread_count": unread_count,
            "has_cv_file": has_cv_file,
            "upcoming_interviews": upcoming_interviews,
            "candidate_applications": candidate_applications,
            "matching_jobs_count": matching_jobs_count,
            "total_active_jobs": total_active_jobs,
            "total_other_jobs": total_other_jobs,
            "total_expired_jobs": total_expired_jobs,
        },
    )
def get_notifications_ajax(request):
    """API trả về danh sách thông báo và số lượng chưa đọc của ứng viên theo thời gian thực"""
    if not request.user.is_authenticated or getattr(request.user, 'is_recruiter', False):
        return JsonResponse({'notifications': [], 'unread_count': 0})
        
    apps = Application.objects.filter(candidate=request.user).order_by('-updated_at')
    
    data = []
    for app in apps:
        data.append({
            'id': app.id,
            'job_title': app.job.title,
            'company_name': app.job.company_name,
            'status_vi': app.get_status_display_vi(),
            'interview_details': app.interview_details or '',
            'updated_at': app.updated_at.strftime('%H:%M %d/%m/%Y'),
        })
        
    return JsonResponse({
        'notifications': data, 
        'unread_count': apps.count()
    })