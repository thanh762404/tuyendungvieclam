from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User, Profile
from .skills import invalid_skills_for_major
from jobs.models import CompanyProfile, RecruiterAccount
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
    company_name = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'placeholder': 'Ví dụ: Công Ty TNHH CT',
            }
        ),
        label='Tên công ty / Doanh nghiệp',
    )
    company_address = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'placeholder': 'Nhập địa chỉ trụ sở công ty',
            }
        ),
        label='Địa chỉ công ty',
    )
    company_website = forms.URLField(
        required=False,
        widget=forms.URLInput(
            attrs={'class': 'form-control', 'placeholder': 'https://'}
        ),
        label='Website công ty',
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
            attrs={
                'placeholder': 'Số điện thoại ',
                'class': 'form-control',
                'maxlength': '10',
                'inputmode': 'numeric',
            }
        ),
        label='Số điện thoại',
    )

    birth_date = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={
                'class': 'form-control',
                'type': 'date',
            }
        ),
        label='Ngày sinh',
    )
    address = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
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
        fields = (
            'email',
            'first_name',
            'last_name',
        )

    def clean_phone(self):
        phone = (self.cleaned_data.get('phone') or '').strip()
        if phone:
            if not re.fullmatch(r'0[0-9]{9}', phone):
                raise forms.ValidationError(
                    'Số điện thoại phải gồm đúng 10 chữ số và bắt đầu bằng số 0 (ví dụ: 0912345678).'
                )
        return phone

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = True

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                'Email này đã được đăng ký. Vui lòng dùng email khác hoặc đăng nhập.'
            )
        return email

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        
        if role == 'candidate':
            self._validate_major_skills(cleaned_data)
        elif role == 'recruiter':
            company_name = (cleaned_data.get('company_name') or '').strip()
            company_address = (cleaned_data.get('company_address') or '').strip()
            cleaned_data['company_name'] = company_name
            cleaned_data['company_address'] = company_address
            if not company_name:
                self.add_error('company_name', 'Vui lòng nhập tên công ty.')
            if not company_address:
                self.add_error('company_address', 'Vui lòng nhập địa chỉ công ty.')
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
        email = self.cleaned_data.get('email')
        user.username = email
        
        role = self.cleaned_data.get('role')
        if role == 'candidate':
            user.is_candidate = True
        elif role == 'recruiter':
            user.is_recruiter = True
            user.is_active = False
            user.recruiter_cv = self.cleaned_data.get('recruiter_cv')

        if commit:
            user.save()
            if role == 'candidate':
                Profile.objects.create(
                    user=user,
                    phone=self.cleaned_data.get('phone'),
                    birth_date=self.cleaned_data.get('birth_date'),
                    address=self.cleaned_data.get('address'),
                    skills=self.cleaned_data.get('skills'),
                    major=self.cleaned_data.get('major'),
                )
            elif role == 'recruiter':
                CompanyProfile.objects.create(
                    user=user,
                    company_name=self.cleaned_data.get('company_name') or 'Nhà tuyển dụng',
                    phone=self.cleaned_data.get('phone'),
                    address=self.cleaned_data.get('company_address'),
                    website=self.cleaned_data.get('company_website'),
                )
                RecruiterAccount.objects.get_or_create(user=user)
        return user


class UserUpdateForm(forms.ModelForm):
    email = forms.EmailField(required=True, label='Email')

    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name']

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if 'email' in self.changed_data:
            if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
                raise forms.ValidationError(
                    'Email này đã được tài khoản khác sử dụng. Vui lòng dùng email khác.'
                )
        return email


class ProfileUpdateForm(forms.ModelForm):
    major = forms.ChoiceField(
        choices=MAJOR_CHOICES, 
        required=False, 
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = Profile
        fields = ['phone', 'birth_date', 'address', 'bio', 'major', 'skills', 'avatar', 'cv_file']
        widgets = {
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'birth_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
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
            'address': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Nhập địa chỉ công ty...',
                }
            ),
            'website': forms.URLInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'company_logo': forms.FileInput(attrs={'class': 'form-control'}),
        }