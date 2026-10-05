from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User, Profile
from .skills import invalid_skills_for_major
from jobs.models import CompanyProfile
import re

# ĐỊNH NGHĨA 6 NGÀNH CHUẨN DÙNG CHUNG CHO TOÀN BỘ HỆ THỐNG
MAJOR_CHOICES = (
    ('', 'Chọn ngành đào tạo'),
    ('Công nghệ thông tin', 'Công nghệ thông tin'),
    ('Quản trị kinh doanh', 'Quản trị kinh doanh'),
    ('Thiết kế đồ họa', 'Thiết kế đồ họa'),
    ('Logistics', 'Logistics'),
    ('Ngôn ngữ Anh', 'Ngôn ngữ Anh'),
    ('Tài chính – Ngân hàng', 'Tài chính – Ngân hàng'),
)


class SignUpForm(UserCreationForm):
    ROLE_CHOICES = (
        ('candidate', 'Ứng viên tìm việc'),
        ('recruiter', 'Nhà tuyển dụng'),
    )
    
    role = forms.ChoiceField(
        choices=ROLE_CHOICES,
        widget=forms.RadioSelect,
        label='Bạn đăng ký với tư cách là',
    )
    recruiter_cv = forms.FileField(
        required=False,
        widget=forms.FileInput(
            attrs={
                'class': 'form-control',
                'accept': '.pdf,.doc,.docx',
            }
        ),
        label='CV xác minh nhà tuyển dụng',
    )
    phone = forms.CharField(
        max_length=15,
        required=True,
        widget=forms.TextInput(
            attrs={'placeholder': 'Số điện thoại', 'class': 'form-control'}
        ),
        label='Số điện thoại',
    )

    major = forms.ChoiceField(
        choices=MAJOR_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Ngành đào tạo',
    )

    skills = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                'placeholder': 'Chọn ngành để hiển thị kỹ năng tương ứng...',
                'class': 'form-control',
                'readonly': True,
            }
        ),
        label='Sở trường / Kỹ năng của bạn',
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = UserCreationForm.Meta.fields + (
            'email',
            'first_name',
            'last_name',
        )

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone:
            if not phone.isdigit() or len(phone) != 10:
                raise forms.ValidationError(
                    'Số điện thoại phải bao gồm đúng 10 chữ số và không chứa ký tự chữ!'
                )
        return phone

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('role') == 'candidate':
            self._validate_major_skills(cleaned_data)
        elif cleaned_data.get('role') == 'recruiter':
            recruiter_cv = cleaned_data.get('recruiter_cv')
            if not recruiter_cv:
                self.add_error('recruiter_cv', 'Vui lòng tải CV để admin xác minh tài khoản.')
            elif recruiter_cv.name.rsplit('.', 1)[-1].lower() not in {'pdf', 'doc', 'docx'}:
                self.add_error('recruiter_cv', 'CV chỉ được dùng định dạng PDF, DOC hoặc DOCX.')
            elif recruiter_cv.size > 10 * 1024 * 1024:
                self.add_error('recruiter_cv', 'Dung lượng CV không được vượt quá 10 MB.')
        return cleaned_data

    def _validate_major_skills(self, cleaned_data):
        invalid_skills = invalid_skills_for_major(
            cleaned_data.get('major'), cleaned_data.get('skills')
        )
        if invalid_skills:
            self.add_error('skills', 'Vui lòng chọn kỹ năng thuộc ngành đào tạo đã chọn.')

    def save(self, commit=True):
        user = super().save(commit=False)
        role = self.cleaned_data.get('role')
        if role == 'candidate':
            user.is_candidate = True
        elif role == 'recruiter':
            user.is_recruiter = True
            user.is_active = False
            user.recruiter_cv = self.cleaned_data.get('recruiter_cv')

        if commit:
            user.save()
            Profile.objects.create(
                user=user,
                phone=self.cleaned_data.get('phone'),
                skills=self.cleaned_data.get('skills'),
                major=self.cleaned_data.get('major'),
            )
        return user


class UserUpdateForm(forms.ModelForm):
    email = forms.EmailField(required=True, label='Email')

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name']


class ProfileUpdateForm(forms.ModelForm):
    # Sử dụng chung bộ 6 ngành chuẩn
    major = forms.ChoiceField(
        choices=MAJOR_CHOICES, 
        required=False, 
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = Profile
        fields = ['phone', 'bio', 'major', 'skills', 'avatar', 'cv_file']
        widgets = {
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'bio': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'skills': forms.TextInput(attrs={'class': 'form-control', 'readonly': True}),
            'avatar': forms.FileInput(attrs={'class': 'form-control'}),
            'cv_file': forms.FileInput(attrs={'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        invalid_skills = invalid_skills_for_major(
            cleaned_data.get('major'), cleaned_data.get('skills')
        )
        if invalid_skills:
            self.add_error('skills', 'Vui lòng chọn kỹ năng thuộc ngành đào tạo đã chọn.')
        return cleaned_data


class CompanyProfileForm(forms.ModelForm):
    class Meta:
        model = CompanyProfile
        fields = ['company_name', 'phone', 'address', 'website', 'description', 'company_logo']
        widgets = {
            'company_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nhập số điện thoại liên hệ...'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'website': forms.URLInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'company_logo': forms.FileInput(attrs={'class': 'form-control'}),
        }