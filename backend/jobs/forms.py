from django import forms
from .models import Application, CompanyProfile, Job, PackageTransaction

MAJOR_CHOICES = [
    ('', '-- Chọn ngành đào tạo --'),
    ('Công nghệ thông tin', 'Công nghệ thông tin'),
    ('Quản trị kinh doanh', 'Quản trị kinh doanh'),
    ('Thiết kế đồ họa', 'Thiết kế đồ họa'),
    ('Logistics', 'Logistics'),
    ('Ngôn ngữ Anh', 'Ngôn ngữ Anh'),
    ('Tài chính – Ngân hàng', 'Tài chính – Ngân hàng'),
]
class JobForm(forms.ModelForm):
    # Khai báo ép kiểu thành dạng chọn thả xuống (Select)
    major_required = forms.ChoiceField(
        choices=MAJOR_CHOICES,
        widget=forms.Select(attrs={"class": "form-select", "id": "id_major_required"}),
        required=False,
        label="Ngành đào tạo"
    )
    
    # Dùng widget ẩn để gom các kỹ năng được tích chọn truyền vào database
    skills_required = forms.CharField(
        widget=forms.HiddenInput(attrs={"id": "id_skills_required"}),
        required=False
    )

    class Meta:
        model = Job
        fields = [
            "title",
            "company_name",
            "major_required",    
            "skills_required",   
            "location",
            "salary",
            "job_type",
            "description",
            "requirements",
            "expires_at",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "company_name": forms.TextInput(attrs={"class": "form-control"}),
            "location": forms.TextInput(attrs={"class": "form-control"}),
            "salary": forms.TextInput(attrs={"class": "form-control"}),
            "job_type": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(
                attrs={"class": "form-control", "rows": 4}
            ),
            "requirements": forms.Textarea(
                attrs={"class": "form-control", "rows": 4}
            ),
            "expires_at": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
        }
class CompanyProfileForm(forms.ModelForm):
    """Form giúp nhà tuyển dụng cập nhật thông tin công ty và tải logo riêng"""

    class Meta:
        model = CompanyProfile
        fields = [
            "company_name",
            "phone",
            "company_logo",
            "address",
            "website",
            "description",
        ]
        widgets = {
            "company_name": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Nhập số điện thoại liên hệ...",
                }
            ),
            "company_logo": forms.FileInput(attrs={"class": "form-control"}),
            "address": forms.TextInput(attrs={"class": "form-control"}),
            "website": forms.URLInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(
                attrs={"class": "form-control", "rows": 4}
            ),
        }


class ApplicationForm(forms.ModelForm):

    class Meta:
        model = Application
        fields = ["cv_file", "cover_letter"]
        widgets = {
            "cv_file": forms.FileInput(attrs={"class": "form-control"}),
            "cover_letter": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Giới thiệu ngắn gọn về bản thân và kinh nghiệm của bạn...",
                }
            ),
        }


class PackagePurchaseForm(forms.ModelForm):
    """Form dùng cho Nhà tuyển dụng chọn gói cước và tải ảnh biên lai chuyển khoản"""

    class Meta:
        model = PackageTransaction
        fields = ["package", "proof_image"]
        widgets = {
            "package": forms.Select(attrs={"class": "form-control"}),
            "proof_image": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }