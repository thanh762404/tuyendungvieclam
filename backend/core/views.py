from django.conf import settings
from django.contrib import messages
from django.core.mail import send_mail
from django.shortcuts import redirect, render

from jobs.models import ContactMessage, Job


def home_view(request):
    # Lấy danh sách việc làm mới nhất từ database (ví dụ lấy 6-10 việc làm mới nhất)
    jobs = Job.objects.all().order_by('-created_at')[:10]  # Thay đổi tùy theo tên trường sắp xếp của bạn

    context = {
        'jobs': jobs,
    }
    return render(request, 'home.html', context)


def about_view(request):
    return render(request, 'pages/about.html')


def contact_view(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        message_content = request.POST.get('message', '').strip()

        if name and email and message_content:
            ContactMessage.objects.create(
                name=name,
                email=email,
                message=message_content,
            )

            try:
                admin_email = getattr(settings, 'ADMIN_EMAIL', settings.EMAIL_HOST_USER)
                send_mail(
                    subject=f"[Yêu cầu hỗ trợ mới] Từ khách hàng: {name}",
                    message=(
                        f"Bạn nhận được một yêu cầu hỗ trợ mới từ hệ thống CTJob:\n\n"
                        f"- Họ và tên: {name}\n"
                        f"- Email: {email}\n"
                        f"- Nội dung: {message_content}\n\n"
                        "Vui lòng truy cập trang Quản trị Admin để phản hồi."
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[admin_email],
                    fail_silently=False,
                )
                messages.success(
                    request,
                    "Gửi câu hỏi thành công! Bộ phận hỗ trợ sẽ phản hồi qua email cho bạn.",
                )
            except Exception as e:
                messages.error(
                    request,
                    f"Lỗi gửi email hỗ trợ: {str(e)}. Vui lòng kiểm tra lại mật khẩu ứng dụng Gmail hoặc cấu hình email.",
                )

            return redirect('contact')

        messages.error(request, 'Vui lòng điền đầy đủ họ tên, email và nội dung.')
        return redirect('contact')

    return render(request, 'pages/contact.html')

def privacy_view(request):
    return render(request, 'pages/privacy.html')

def terms_view(request):
    return render(request, 'pages/terms.html')

def cam_nang_cv(request):
    return render(request, 'cam_nang/viet_cv.html')

def cam_nang_phong_van(request):
    return render(request, 'cam_nang/phong_van.html')

def cam_nang_dinh_huong(request):
    return render(request, 'cam_nang/dinh_huong.html')

def cam_nang_thi_truong(request):
    return render(request, 'cam_nang/thi_truong.html')