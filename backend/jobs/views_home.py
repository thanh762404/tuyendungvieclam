import re
from datetime import datetime
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from accounts.services import extract_skills_from_file

from .models import Application, Job, JobChatMessage


def extract_text_from_cv(file_path):
    text = ''
    try:
        if file_path.lower().endswith('.pdf'):
            from pypdf import PdfReader

            with open(file_path, 'rb') as file:
                text = ' '.join(page.extract_text() or '' for page in PdfReader(file).pages)
        elif file_path.lower().endswith('.docx'):
            from docx import Document

            document = Document(file_path)
            text = ' '.join(paragraph.text for paragraph in document.paragraphs)
    except Exception:
        pass
    return text.lower()


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
    cv_skills = []
    candidate_major = ''
    has_cv_file = False

    if request.user.is_authenticated and getattr(request.user, "is_candidate", False):
        try:
            profile = request.user.profile
            candidate_major = _normalize_match_text(profile.major)
            profile_skills.extend(_split_skills(profile.skills))

            if profile.cv_file and profile.cv_file.name:
                has_cv_file = True
                cv_skills.extend(_split_skills(profile.cv_skills))
                try:
                    cv_skills.extend(extract_skills_from_file(profile.cv_file))
                except Exception:
                    pass
        except Exception:
            pass

    # An explicit skill filter replaces profile skills but retains the selected major.
    if selected_skill_filter:
        profile_skills = _split_skills(selected_skill_filter)

    suggested_jobs = []
    other_jobs = []
    user_skills = list(dict.fromkeys(profile_skills + cv_skills))
    normalized_profile_skills = {
        _normalize_skill(skill) for skill in profile_skills if skill.strip()
    }
    normalized_cv_skills = {
        _normalize_skill(skill) for skill in cv_skills if skill.strip()
    }
    scored_suggestions = []
    for job in active_jobs:
        job_major = _normalize_match_text(job.major_required)
        major_matches = not job_major or (candidate_major and job_major == candidate_major)
        required_skills = {
            _normalize_skill(skill) for skill in _split_skills(job.skills_required)
        }
        if required_skills:
            matched_profile_skills = normalized_profile_skills & required_skills
            matched_cv_skills = normalized_cv_skills & required_skills
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
            matched_cv_skills = {
                skill for skill in normalized_cv_skills
                if _contains_skill(job_title, skill)
            }
            title_skills = matched_profile_skills | matched_cv_skills

        matched_skills = matched_profile_skills | matched_cv_skills
        skill_coverage = len(matched_skills) / len(required_skills) if required_skills else bool(matched_skills)
        profile_title_match = bool(normalized_profile_skills & title_skills)
        cv_title_match = bool(normalized_cv_skills & title_skills)
        profile_skill_match = bool(matched_profile_skills)
        cv_skill_match = has_cv_file and bool(matched_cv_skills)
        has_candidate_skills = bool(normalized_profile_skills or normalized_cv_skills)
        major_only_match = not has_candidate_skills and candidate_major and job_major == candidate_major

        if not query and (major_matches or cv_skill_match) and (
            profile_skill_match or cv_skill_match or major_only_match
        ):
            job.recommendation_profile_skills = _matched_skill_labels(
                profile_skills, matched_profile_skills
            )
            job.recommendation_cv_skills = _matched_skill_labels(
                cv_skills, matched_cv_skills
            )
            job.recommendation_score = round(skill_coverage * 100)
            scored_suggestions.append((
                (
                    bool(matched_profile_skills),
                    len(matched_profile_skills),
                    skill_coverage,
                    len(matched_cv_skills),
                    profile_title_match or cv_title_match,
                    bool(job_major),
                ),
                job,
            ))
        else:
            other_jobs.append(job)

    scored_suggestions.sort(key=lambda item: item[0], reverse=True)
    suggested_jobs = [job for _, job in scored_suggestions]

    unread_count = 0
    upcoming_interviews = None

    if request.user.is_authenticated and getattr(request.user, "is_candidate", False):
        unread_count = JobChatMessage.objects.filter(
            receiver=request.user,
            is_application_update=True,
            is_read=False,
        ).count()
        
        candidate_apps = Application.objects.filter(
            candidate=request.user,
            interview_details__isnull=False
        ).exclude(interview_details="")
        
        now = timezone.now()
        
        for app in candidate_apps:
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

    return render(
        request,
        "home.html",
        {
            "jobs": active_jobs,
            "suggested_jobs": suggested_jobs,
            "other_jobs": other_jobs,
            "expired_jobs": expired_jobs,
            "query": query,
            "location": location,
            "user_skills": ", ".join(user_skills),
            "selected_skills": selected_skill_filter,
            "unread_count": unread_count,
            "has_cv_file": has_cv_file,
            "upcoming_interviews": upcoming_interviews,
        },
    )