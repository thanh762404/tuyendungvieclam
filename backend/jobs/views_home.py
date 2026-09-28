import os
import re
from datetime import datetime, timedelta
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

# Thư viện AI / Toán học tính độ tương đồng ngữ nghĩa tự động
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .models import Application, Job


def extract_text_from_cv(file_path):
    text = ""
    if file_path.endswith(".pdf"):
        try:
            with open(file_path, "rb") as f:
                from PyPDF2 import PdfReader
                reader = PdfReader(f)
                for page in reader.pages:
                    text += page.extract_text() or ""
        except Exception:
            pass
    elif file_path.endswith(".docx"):
        try:
            from docx import Document
            doc = Document(file_path)
            for para in doc.paragraphs:
                text += para.text + " "
        except Exception:
            pass
    return text.lower()


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

    # 1. Thu thập thông tin kỹ năng của ứng viên từ Profile hoặc CV
    user_skills_text = ""
    has_cv_file = False

    if request.user.is_authenticated and getattr(request.user, "is_candidate", False):
        try:
            profile = request.user.profile
            if profile.skills:
                user_skills_text += profile.skills + " "

            if profile.cv_file and profile.cv_file.name:
                has_cv_file = True
                try:
                    cv_path = profile.cv_file.path
                    if os.path.exists(cv_path):
                        user_skills_text += extract_text_from_cv(cv_path) + " "
                except Exception:
                    pass
        except Exception:
            pass

    # Nếu người dùng có chọn bộ lọc kỹ năng trên giao diện, ưu tiên dùng bộ lọc đó
    if selected_skill_filter:
        user_skills_text = selected_skill_filter

    suggested_jobs = []
    other_jobs = []

    # 2. THUẬT TOÁN AI TỰ ĐỘNG (TF-IDF & COSINE SIMILARITY)
    # Nếu ứng viên có kỹ năng/CV và không dùng ô tìm kiếm chung
    if user_skills_text.strip() and not query and active_jobs:
        try:
            # Gom toàn bộ nội dung của các việc làm (Tiêu đề + Mô tả + Yêu cầu)
            job_corpus = []
            for job in active_jobs:
                job_text = f"{job.title} {getattr(job, 'description', '')} {getattr(job, 'requirements', '')}"
                job_corpus.append(job_text)

            # Thêm chuỗi kỹ năng của ứng viên vào danh sách phân tích
            documents = [user_skills_text] + job_corpus

            # Dùng TF-IDF Vectorizer để chuyển đổi văn bản thành ma trận tần suất từ khóa
            vectorizer = TfidfVectorizer(stop_words='english', lowercase=True)
            tfidf_matrix = vectorizer.fit_transform(documents)

            # Tính toán độ tương đồng cosine giữa kỹ năng của ứng viên (dòng 0) với từng công việc (từ dòng 1 trở đi)
            cosine_sim = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:]).flatten()

            # Phân loại công việc dựa trên ngưỡng tương đồng (Similarity Score > 0.03 nghĩa là có liên quan)
            for idx, job in enumerate(active_jobs):
                score = cosine_sim[idx]
                if score > 0.025: # Ngưỡng tự động nhận diện mối liên quan
                    suggested_jobs.append(job)
                else:
                    other_jobs.append(job)
        except Exception:
            # Trường hợp có lỗi ngoại lệ tính toán, trả về mặc định để không sập web
            other_jobs = active_jobs
    else:
        other_jobs = active_jobs
        suggested_jobs = []

    unread_count = 0
    upcoming_interviews = None

    if request.user.is_authenticated:
        unread_count = Application.objects.filter(candidate=request.user).count()
        
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
            "user_skills": user_skills_text.strip(),
            "selected_skills": selected_skill_filter,
            "unread_count": unread_count,
            "has_cv_file": has_cv_file,
            "upcoming_interviews": upcoming_interviews,
        },
    )