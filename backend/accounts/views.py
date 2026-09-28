from datetime import timedelta
import os
from pypdf import PdfReader
from docx import Document

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from jobs.forms import ApplicationForm, JobForm, CompanyProfileForm
from jobs.models import Application, Job, CompanyProfile

from .forms import ProfileUpdateForm, SignUpForm, UserUpdateForm
from .models import Profile

def extract_skills_from_file(file_field):
    """Hàm hỗ trợ đọc file CV (PDF hoặc Word) và trích xuất kỹ năng."""
    text = ""
    if not file_field:
        return []
        
    file_extension = os.path.splitext(file_field.name)[1].lower()
    try:
        if file_extension == '.pdf':
            reader = PdfReader(file_field)
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
        elif file_extension in ['.docx', '.doc']:
            doc = Document(file_field)
            for para in doc.paragraphs:
                text += para.text + "\n"
    except Exception as e:
        print("Lỗi đọc file CV:", e)
    
    text = text.lower()
    
    keyword_pool = [
        'python', 'django', 'tester', 'nodejs', 'reactjs', 'sql', 'java', 'c#', 'php',
        'data engineering', 'data analysis', 'data analyst', 'business intelligence',
        'pandas', 'numpy', 'postgresql', 'power bi', 'excel', 'ui/ux', 'figma',
        'photoshop', 'illustrator', 'marketing', 'sales', 'seo', 'social media',
        'google ads', 'facebook ads', 'kế toán', 'accounting', 'finance', 'banking',
        'customer service', 'tiếng anh', 'english', 'hotel', 'tourism', 'devops',
        'javascript', 'html5', 'css3', 'flask', 'angular', 'vuejs', 'fullstack'
    ]
    
    found_skills = []
    for skill in keyword_pool:
        if skill in text:
            found_skills.append(skill)
            
    return found_skills


def signup_view(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.date_joined = timezone.now()
            user.save()

            role = form.cleaned_data.get('role')
            if role == 'recruiter':
                CompanyProfile.objects.get_or_create(
                    user=user,
                    defaults={
                        'company_name': user.username,
                        'phone': form.cleaned_data.get('phone', '')
                    }
                )
            else:
                profile, created = Profile.objects.get_or_create(user=user)
                profile.phone = form.cleaned_data.get('phone', '')
                profile.major = form.cleaned_data.get('major', '')
                profile.skills = form.cleaned_data.get('skills', '')
                profile.save()

            return redirect('login')
    else:
        form = SignUpForm()
    return render(request, 'accounts/signup.html', {'form': form})


def login_view(request):
    google_client_id = os.getenv('SOCIAL_GOOGLE_CLIENT_ID', '').strip()
    google_secret = os.getenv('SOCIAL_GOOGLE_SECRET', '').strip()
    facebook_app_id = os.getenv('SOCIAL_FACEBOOK_APP_ID', '').strip()
    facebook_secret = os.getenv('SOCIAL_FACEBOOK_SECRET', '').strip()

    google_login_enabled = bool(google_client_id and google_secret)
    facebook_login_enabled = bool(facebook_app_id and facebook_secret)

    provider = request.GET.get('provider')
    if provider == 'google' and not google_login_enabled:
        messages.info(request, 'Google Login đang được tích hợp. Vui lòng thêm Client ID và Secret để kích hoạt chức năng này.')
    elif provider == 'facebook' and not facebook_login_enabled:
        messages.info(request, 'Facebook Login đang được tích hợp. Vui lòng thêm App ID và Secret để kích hoạt chức năng này.')

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                user.last_login = timezone.now()
                user.save(update_fields=['last_login'])

                # Phân quyền chuyển hướng thông minh dựa trên 3 loại tài khoản
                if user.is_staff or user.is_superuser:
                    return redirect('custom_admin_dashboard')
                elif getattr(user, 'is_recruiter', False):
                    return redirect('recruiter_job_list')
                else:
                    return redirect('home')
    else:
        form = AuthenticationForm()

    context = {
        'form': form,
        'google_login_enabled': google_login_enabled,
        'facebook_login_enabled': facebook_login_enabled,
    }
    return render(request, 'accounts/login.html', context)


def logout_view(request):
    logout(request)
    return redirect('login')


def home_view(request):
    # Nếu Admin hoặc Nhà tuyển dụng cố tình vào trang chủ tìm việc, có thể điều hướng họ về khu vực riêng (Tùy chọn)
    if request.user.is_authenticated:
        if request.user.is_staff or request.user.is_superuser:
            return redirect('custom_admin_dashboard')

    query = request.GET.get('q', '')
    location = request.GET.get('location', '')

    now = timezone.now()
    all_jobs = Job.objects.filter(status='Approved').order_by('-created_at')

    if query:
        all_jobs = all_jobs.filter(
            Q(title__icontains=query)
            | Q(company_name__icontains=query)
            | Q(description__icontains=query)
        )
    if location:
        all_jobs = all_jobs.filter(location__icontains=location)

    suggested_jobs = []
    other_jobs = []
    expired_jobs = []

    three_days_ago = now - timedelta(days=3)

    for job in all_jobs:
        is_job_expired = (
            job.is_expired
            if hasattr(job, 'is_expired')
            else (job.expires_at and job.expires_at < now)
        )
        job.is_expired_status = is_job_expired

        if not is_job_expired and job.created_at:
            if job.created_at >= three_days_ago:
                job.is_new_status = True
            else:
                job.is_new_status = False
        else:
            job.is_new_status = False

        if is_job_expired:
            expired_jobs.append(job)
        else:
            other_jobs.append(job)

    if (
        request.user.is_authenticated
        and getattr(request.user, 'is_candidate', False)
        and not query
    ):
        try:
            profile = request.user.profile
            
            combined_skills = []
            if profile.skills:
                combined_skills.extend([s.strip().lower() for s in profile.skills.split(',') if s.strip()])
            
            if profile.cv_file:
                try:
                    cv_skills = [s.lower() for s in extract_skills_from_file(profile.cv_file)]
                    combined_skills.extend(cv_skills)
                except Exception:
                    pass

            skill_list = list(set(combined_skills))

            if skill_list:
                temp_other = list(other_jobs)
                for job in temp_other:
                    matched = any(
                        skill in job.title.lower() or skill in job.description.lower()
                        for skill in skill_list
                    )
                    if matched:
                        suggested_jobs.append(job)
                        if job in other_jobs:
                            other_jobs.remove(job)
        except Exception:
            pass

    return render(
        request,
        'accounts/home.html',
        {
            'suggested_jobs': suggested_jobs,
            'other_jobs': other_jobs,
            'expired_jobs': expired_jobs,
            'query': query,
            'location': location,
        },
    )


@login_required
def recruiter_job_list(request):
    jobs = Job.objects.filter(recruiter=request.user).order_by('-created_at')
    return render(request, 'jobs/recruiter_job_list.html', {'jobs': jobs})


@login_required
def profile_view(request):
    user = request.user
    suggested_jobs = []
    company_profile = None
    profile = None
    
    if getattr(user, 'is_recruiter', False):
        company_profile, created = CompanyProfile.objects.get_or_create(
            user=user,
            defaults={"company_name": user.username}
        )
    else:
        profile, created = Profile.objects.get_or_create(user=user)

    context = {
        'suggested_jobs': suggested_jobs,
        'company_profile': company_profile,
        'profile': profile,
        'is_recruiter': getattr(user, 'is_recruiter', False),
    }
    return render(request, 'accounts/profile.html', context)


@login_required
def profile_edit_view(request):
    user = request.user
    
    if getattr(user, 'is_recruiter', False):
        company_profile, created = CompanyProfile.objects.get_or_create(
            user=user,
            defaults={"company_name": user.username}
        )
        if request.method == 'POST':
            p_form = CompanyProfileForm(request.POST, request.FILES, instance=company_profile)
            u_form = UserUpdateForm(request.POST, instance=user)
            
            if p_form.is_valid() and u_form.is_valid():
                p_form.save()
                u_form.save()
                messages.success(request, "Cập nhật thông tin công ty thành công!")
                return redirect('profile')
            else:
                messages.error(request, "Không thể lưu! Vui lòng kiểm tra lại thông tin nhập.")
        else:
            p_form = CompanyProfileForm(instance=company_profile)
            u_form = UserUpdateForm(instance=user)
            
        context = {'u_form': u_form, 'p_form': p_form, 'is_recruiter': True}
        return render(request, 'accounts/profile_edit.html', context)
    
    else:
        profile, created = Profile.objects.get_or_create(user=user)
        if request.method == 'POST':
            u_form = UserUpdateForm(request.POST, instance=user)
            p_form = ProfileUpdateForm(request.POST, request.FILES, instance=profile)

            if u_form.is_valid() and p_form.is_valid():
                user_profile = p_form.save(commit=False)
                if request.POST.get('cv_file-clear') or ('cv_file' in request.FILES and not request.FILES['cv_file']):
                    user_profile.cv_file = None
                user_profile.save()
                u_form.save()
                messages.success(request, "Cập nhật hồ sơ thành công!")
                return redirect('profile')
            else:
                messages.error(request, "Không thể lưu hồ sơ ứng viên. Vui lòng kiểm tra lại.")
        else:
            u_form = UserUpdateForm(instance=user)
            p_form = ProfileUpdateForm(instance=profile)

        context = {'u_form': u_form, 'p_form': p_form, 'is_recruiter': False}
        return render(request, 'accounts/profile_edit.html', context)