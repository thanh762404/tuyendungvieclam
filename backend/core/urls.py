from django.contrib import admin
from django.urls import path, include
from jobs.views import home_view  
from django.conf import settings
from django.conf.urls.static import static
from core import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home_view, name='home'),
    path('accounts/', include('accounts.urls')),
    path('social/', include('allauth.urls')),
    path('', include('jobs.urls')),  # Giữ lại duy nhất dòng này để tránh lặp path (bỏ path('jobs/', include('jobs.urls')) đi)

    # Các trang thông tin tĩnh
    path('gioi-thieu/', views.about_view, name='about'),
    path('lien-he/', views.contact_view, name='contact'),
    path('chinh-sach-bao-mat/', views.privacy_view, name='privacy'),
    path('dieu-khoan-dich-vu/', views.terms_view, name='terms'), 
    path('cam-nang/viet-cv/', views.cam_nang_cv, name='cam_nang_cv'),
    path('cam-nang/phong-van/', views.cam_nang_phong_van, name='cam_nang_phong_van'),
    path('cam-nang/dinh-huong/', views.cam_nang_dinh_huong, name='cam_nang_dinh_huong'),
    path('cam-nang/thi-truong/', views.cam_nang_thi_truong, name='cam_nang_thi_truong'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)