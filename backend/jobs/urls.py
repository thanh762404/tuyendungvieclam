from django.urls import path
from . import views
from . import views_admin
from .views_payments import sepay_webhook
from .views_candidate import (
    delete_all_notifications_ajax,
    delete_notification_ajax,
    get_notifications_ajax,
    mark_all_notifications_read_ajax,
    mark_notification_read_ajax,
)

urlpatterns = [
    path('webhooks/sepay/', sepay_webhook, name='sepay_webhook'),
    path('buy-package/transactions/<int:pk>/status/', views.package_transaction_status, name='package_transaction_status'),
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
    
    # 👉 ĐƯỜNG DẪN API THÔNG BÁO REALTIME (GỌI TRỰC TIẾP HÀM ĐÃ IMPORT)
    path('api/notifications/', get_notifications_ajax, name='get_notifications_ajax'),
    path('api/notifications/mark-read/', mark_notification_read_ajax, name='mark_notification_read_ajax'),
    path('api/notifications/mark-read-all/', mark_all_notifications_read_ajax, name='mark_all_notifications_read_ajax'),
    path('api/notifications/delete/', delete_notification_ajax, name='delete_notification_ajax'),
    path('api/notifications/delete-all/', delete_all_notifications_ajax, name='delete_all_notifications_ajax'),
    
    # Các đường dẫn chi tiết công việc và chat
    path('jobs/<int:pk>/apply/', views.apply_job, name='apply_job'),
    path('jobs/<int:pk>/applications/', views.job_applications, name='job_applications'),
    path('jobs/<int:pk>/chat/send/', views.send_job_chat_message, name='send_job_chat_message'),
    path('jobs/<int:pk>/chat/history/', views.get_job_chat_history, name='get_job_chat_history'),
    path('jobs/<int:pk>/chat/<int:candidate_id>/delete-conversation/', views.delete_job_chat_conversation, name='delete_job_chat_conversation'),
    path('jobs/<int:pk>/chat/unread-count/', views.get_job_chat_unread_count, name='get_job_chat_unread_count'),
    path('jobs/<int:pk>/chat/mark-read/', views.mark_job_chat_read, name='mark_job_chat_read'),
    path('jobs/<int:pk>/', views.job_detail, name='job_detail'),
    
    # Khu vực Admin tùy chỉnh
    path('custom-admin/', views.custom_admin_dashboard, name='custom_admin_dashboard'),
    path('custom-admin/users/', views.admin_manage_users, name='admin_manage_users'),
    path('custom-admin/user/<int:pk>/delete/', views.admin_delete_user, name='admin_delete_user'),
    path('custom-admin/user/<int:pk>/recruiter-cv/', views.admin_recruiter_cv, name='admin_recruiter_cv'),
    path('custom-admin/user/<int:pk>/approve-recruiter/', views.admin_approve_recruiter, name='admin_approve_recruiter'),
    path('custom-admin/user/<int:pk>/reject-recruiter/', views.admin_reject_recruiter, name='admin_reject_recruiter'),
    path('custom-admin/jobs/', views.admin_manage_jobs, name='admin_manage_jobs'),
    path('custom-admin/job/<int:pk>/delete/', views.admin_delete_job, name='admin_delete_job'),
    path('custom-admin/applications/', views.admin_manage_applications, name='admin_manage_applications'),
    path('custom-admin/applications/delete/<int:pk>/', views.admin_delete_application, name='admin_delete_application'),
    path('custom-admin/contact/reply/<int:pk>/', views.admin_reply_contact_action, name='admin_reply_contact_action'),
    path('custom-admin/contacts/delete-resolved/', views.admin_delete_resolved_contacts, name='admin_delete_resolved_contacts'),
    path('custom-admin/transactions/', views_admin.admin_manage_transactions, name='admin_manage_transactions'),
    path('custom-admin/transactions/reject/<int:pk>/', views_admin.admin_reject_transaction, name='admin_reject_transaction'),
]