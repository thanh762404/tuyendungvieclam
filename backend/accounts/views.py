from datetime import timedelta
import os

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from jobs.forms import ApplicationForm, JobForm, CompanyProfileForm
from jobs.models import Application, Job, CompanyProfile
from django.contrib.auth.hashers import make_password
from .forms import ProfileUpdateForm, SignUpForm, UserUpdateForm
from .models import Profile

def signup_view(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                with transaction.atomic():
                    # 1. Lưu thông tin tài khoản cơ bản (User)
                    user = form.save(commit=False)
                    user.date_joined = timezone.now()
                    
                    # ---> THÊM ĐOẠN NÀY ĐỂ BẮT BUỘC LƯU VÀ MÃ HÓA MẬT KHẨU <---
                    password = form.cleaned_data.get('password')
                    if password:
                        user.set_password(password) # Hàm này giúp mã hóa mật khẩu chuẩn của Django
                    # ---------------------------------------------------------
                    
                    user.save() # Lúc này CSDL sẽ nhận được mật khẩu đã mã hóa

                    # 2. Lấy role (vai trò) người dùng đã chọn
                    role = form.cleaned_data.get('role')
                    
                    # 3. Phân tách lưu dữ liệu vào Profile tương ứng
                    if role == 'recruiter' or getattr(user, 'is_recruiter', False):
                        # Lưu thông tin cho Nhà tuyển dụng vào CompanyProfile
                        company_profile, created = CompanyProfile.objects.get_or_create(
                            user=user,
                            defaults={
                                'company_name': form.cleaned_data.get('company_name') or 'Nhà tuyển dụng',
                                'phone': form.cleaned_data.get('phone', ''),
                                'address': form.cleaned_data.get('company_address', ''),
                                'website': form.cleaned_data.get('company_website', ''),
                            }
                        )
                        company_profile.company_name = form.cleaned_data.get('company_name') or company_profile.company_name
                        company_profile.phone = form.cleaned_data.get('phone', company_profile.phone)
                        company_profile.address = form.cleaned_data.get('company_address', company_profile.address)
                        company_profile.website = form.cleaned_data.get('company_website', company_profile.website)
                            
                        company_profile.save()
                    else:
                        # Lưu thông tin cho Ứng viên vào Profile cá nhân
                        profile, created = Profile.objects.get_or_create(user=user)
                        profile.phone = form.cleaned_data.get('phone', '')
                        profile.birth_date = form.cleaned_data.get('birth_date')
                        profile.address = form.cleaned_data.get('address', '')
                        profile.major = form.cleaned_data.get('major', '')
                        profile.skills = form.cleaned_data.get('skills', '')
                        
                        cv_file = request.FILES.get('cv_file')
                        if cv_file:
                            profile.cv_file = cv_file
                            
                        profile.save()

            except IntegrityError as error:
                error_text = str(error).casefold()
                if 'email' not in error_text or not any(
                    marker in error_text for marker in ('duplicate', 'unique', '1062')
                ):
                    raise
                form.add_error(
                    'email',
                    'Email này đã được sử dụng. Vui lòng chọn email khác.',
                )
            else:
                if getattr(user, 'is_recruiter', False):
                    messages.info(
                        request,
                        'Đăng ký thành công. Tài khoản sẽ đăng nhập được sau khi admin duyệt CV.',
                    )
                else:
                    messages.success(request, 'Đăng ký tài khoản thành công!')
                return redirect('login')
    else:
        form = SignUpForm()
    return render(request, 'accounts/signup.html', {'form': form})

def login_view(request):
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

                # --- XỬ LÝ TÍNH NĂNG NHỚ TÀI KHOẢN (REMEMBER ME) ---
                remember_me = request.POST.get('remember_me')
                if remember_me:
                    request.session.set_expiry(1209600)  # 14 ngày
                else:
                    request.session.set_expiry(0)        # Đóng trình duyệt là mất session
                # ----------------------------------------------------

                if user.is_staff or user.is_superuser:
                    return redirect('custom_admin_dashboard')
                elif getattr(user, 'is_recruiter', False):
                    return redirect('recruiter_job_list')
                else:
                    return redirect('home')
    else:
        form = AuthenticationForm()

    return render(request, 'accounts/login.html', {'form': form})


def password_reset_view(request):
    """Xử lý kiểm tra Email hoặc Số điện thoại, nếu đúng chuyển sang trang nhập mật khẩu mới"""
    if request.method == 'POST':
        recovery_input = request.POST.get('recovery_input', '').strip()
        
        User = get_user_model()
        
        # Tìm user theo email
        matched_user = User.objects.filter(email__iexact=recovery_input).first()
        
        # Nếu không thấy theo email, tìm theo số điện thoại trong Profile hoặc CompanyProfile
        if not matched_user:
            try:
                profile_user = Profile.objects.filter(phone__iexact=recovery_input).first()
                if profile_user:
                    matched_user = profile_user.user
                else:
                    company_user = CompanyProfile.objects.filter(phone__iexact=recovery_input).first()
                    if company_user:
                        matched_user = company_user.user
            except Exception:
                pass

        if matched_user:
            # Chuyển hướng sang trang nhập mật khẩu mới và truyền ID của user này đi
            return redirect('password_reset_confirm', user_id=matched_user.id)
        else:
            messages.error(
                request, 
                f"Email hoặc số điện thoại '{recovery_input}' không tồn tại trong hệ thống. Vui lòng kiểm tra lại!"
            )
            return render(request, 'accounts/password_reset.html')
        
    return render(request, 'accounts/password_reset.html')


def password_reset_confirm_view(request, user_id):
    """Trang cho phép nhập mật khẩu mới trực tiếp"""
    User = get_user_model()
    target_user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')

        if not new_password or not confirm_password:
            messages.error(request, "Vui lòng nhập đầy đủ thông tin mật khẩu mới.")
        elif new_password != confirm_password:
            messages.error(request, "Mật khẩu nhập lại không khớp. Vui lòng kiểm tra lại.")
        elif len(new_password) < 6:
            messages.error(request, "Mật khẩu phải có ít nhất 6 ký tự.")
        else:
            # Cập nhật mật khẩu mới được mã hóa an toàn vào database
            target_user.password = make_password(new_password)
            target_user.save()
            messages.success(request, "Đặt lại mật khẩu thành công! Bạn có thể đăng nhập bằng mật khẩu mới.")
            return redirect('login')

    return render(request, 'accounts/password_reset_confirm.html', {'target_user': target_user})

def logout_view(request):
    logout(request)
    return redirect('login')


def home_view(request):
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
            
            skill_list = []
            if profile.skills:
                skill_list = [s.strip().lower() for s in profile.skills.split(',') if s.strip()]

            candidate_major = (profile.major or '').strip().lower()

            if skill_list or candidate_major:
                temp_other = list(other_jobs)
                for job in temp_other:
                    job_title_lower = job.title.lower()
                    job_desc_lower = job.description.lower()
                    
                    matched = False
                    
                    if skill_list:
                        matched = any(
                            skill in job_title_lower or skill in job_desc_lower
                            for skill in skill_list
                        )
                    elif candidate_major:
                        matched = candidate_major in job_title_lower or candidate_major in job_desc_lower

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
            defaults={"company_name": "Nhà tuyển dụng"}
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
            defaults={"company_name": "Nhà tuyển dụng"}
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
            old_cv_name = profile.cv_file.name if profile.cv_file else ''
            old_cv_storage = profile.cv_file.storage if profile.cv_file else None

            if u_form.is_valid() and p_form.is_valid():
                user_profile = p_form.save(commit=False)
                cv_was_cleared = bool(request.POST.get('cv_file-clear'))
                
                if cv_was_cleared:
                    user_profile.cv_file = None

                user_profile.save()
                new_cv_name = user_profile.cv_file.name if user_profile.cv_file else ''
                if old_cv_name and old_cv_name != new_cv_name and old_cv_storage:
                    old_cv_storage.delete(old_cv_name)
                    
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