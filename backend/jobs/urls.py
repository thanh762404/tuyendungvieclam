from django.urls import path
from . import views
from . import views_admin

urlpatterns = [
    # Quản lý tin tuyển dụng của Nhà tuyển dụng
    path('recruiter/jobs/', views.recruiter_job_list, name='recruiter_job_list'),
    path('recruiter/jobs/<int:pk>/achieved-candidates/', views.job_achieved_candidates_view, name='job_achieved_candidates'),
    path('recruiter/jobs/create/', views.job_create, name='job_create'),
    path('recruiter/jobs/<int:pk>/delete/', views.job_delete, name='job_delete'),
    path('recruiter/job/edit/<int:pk>/', views.job_edit, name='job_edit'),
    path('recruiter/job/clone/<int:pk>/', views.job_clone, name='job_clone'),
    path('recruiter/profile/', views.recruiter_profile_view, name='recruiter_profile'),
    path('buy-package/', views.buy_package_view, name='buy_package'),
    path('recruiter/all-approved-candidates/', views.all_approved_candidates_view, name='all_approved_candidates'),
    
    
    # Khu vực Ứng viên (Đã gộp và sửa tránh trùng lặp)
    path('my-applications/', views.my_applications_view, name='my_applications'),
    path('candidate-applications/', views.candidate_applications, name='candidate_applications'),
    path('application/<int:pk>/update/', views.update_application_status, name='update_application_status'),
    
    # Các đường dẫn chi tiết công việc và chat (Giữ chuẩn tiền tố jobs/ khớp với JavaScript fetch)
    path('jobs/<int:pk>/apply/', views.apply_job, name='apply_job'),
    path('jobs/<int:pk>/applications/', views.job_applications, name='job_applications'),
    path('jobs/<int:pk>/chat/send/', views.send_job_chat_message, name='send_job_chat_message'),
    path('jobs/<int:pk>/chat/history/', views.get_job_chat_history, name='get_job_chat_history'),
    path('jobs/<int:pk>/chat/unread-count/', views.get_job_chat_unread_count, name='get_job_chat_unread_count'),
    path('jobs/<int:pk>/chat/mark-read/', views.mark_job_chat_read, name='mark_job_chat_read'),
    path('jobs/<int:pk>/', views.job_detail, name='job_detail'),
    
    # Khu vực Admin tùy chỉnh
    path('custom-admin/', views.custom_admin_dashboard, name='custom_admin_dashboard'),
    path('custom-admin/users/', views.admin_manage_users, name='admin_manage_users'),
    path('custom-admin/user/<int:pk>/delete/', views.admin_delete_user, name='admin_delete_user'),
    path('custom-admin/user/<int:pk>/recruiter-cv/', views.admin_recruiter_cv, name='admin_recruiter_cv'),
    path('custom-admin/user/<int:pk>/approve-recruiter/', views.admin_approve_recruiter, name='admin_approve_recruiter'),
    path('custom-admin/jobs/', views.admin_manage_jobs, name='admin_manage_jobs'),
    path('custom-admin/job/<int:pk>/status/', views.admin_update_job_status, name='admin_update_job_status'),
    path('custom-admin/job/<int:pk>/delete/', views.admin_delete_job, name='admin_delete_job'),
    path('custom-admin/applications/', views.admin_manage_applications, name='admin_manage_applications'),
    path('custom-admin/applications/delete/<int:pk>/', views.admin_delete_application, name='admin_delete_application'),
    path('custom-admin/contact/reply/<int:pk>/', views.admin_reply_contact_action, name='admin_reply_contact_action'),
    path('custom-admin/contacts/delete-resolved/', views.admin_delete_resolved_contacts, name='admin_delete_resolved_contacts'),
    path('custom-admin/transactions/', views_admin.admin_manage_transactions, name='admin_manage_transactions'),
    path('custom-admin/transactions/approve/<int:pk>/', views_admin.admin_approve_transaction, name='admin_approve_transaction'),
    path('custom-admin/transactions/reject/<int:pk>/', views_admin.admin_reject_transaction, name='admin_reject_transaction'),
]