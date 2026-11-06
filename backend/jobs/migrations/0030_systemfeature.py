from django.db import migrations, models


FEATURES = [
    ("candidate-register", "Đăng ký", "Ứng viên", "tables", "accounts_user", "Tài khoản và vai trò được lưu trong User."),
    ("candidate-login", "Đăng nhập", "Ứng viên", "tables", "accounts_user, django_session", "Dùng xác thực Django."),
    ("candidate-profile", "Quản lý hồ sơ và CV", "Ứng viên", "tables", "accounts_profile, accounts_user", ""),
    ("candidate-news", "Trang chủ tin tức / cẩm nang", "Ứng viên", "static", "", "Nội dung hiện nằm trong frontend/templates/cam_nang/*.html, chưa lưu trong CSDL."),
    ("candidate-job-search", "Tìm kiếm việc làm", "Ứng viên", "derived", "jobs_job", "Kết quả được lọc từ bảng tin tuyển dụng."),
    ("candidate-job-recommendations", "Gợi ý việc làm", "Ứng viên", "derived", "accounts_profile, jobs_job", "Gợi ý được tính từ ngành và kỹ năng hồ sơ với yêu cầu tuyển dụng."),
    ("candidate-apply", "Ứng tuyển xin việc", "Ứng viên", "tables", "jobs_application, jobs_job, accounts_user", ""),
    ("candidate-track-application", "Theo dõi ứng tuyển", "Ứng viên", "derived", "jobs_application", "Trạng thái ứng tuyển nằm trong jobs_application."),
    ("candidate-notifications", "Nhận thông báo", "Ứng viên", "tables", "jobs_notification, jobs_jobchatmessage", ""),
    ("candidate-chat-recruiter", "Chat với nhà tuyển dụng", "Ứng viên", "tables", "jobs_jobchatmessage", ""),
    ("recruiter-register", "Đăng ký", "Nhà tuyển dụng", "tables", "accounts_user", "Tài khoản và vai trò được lưu trong User."),
    ("recruiter-login", "Đăng nhập", "Nhà tuyển dụng", "tables", "accounts_user, django_session", "Dùng xác thực Django."),
    ("recruiter-company-profile", "Quản lý thông tin doanh nghiệp", "Nhà tuyển dụng", "tables", "jobs_companyprofile, accounts_user", ""),
    ("recruiter-post-job", "Đăng tin tuyển dụng", "Nhà tuyển dụng", "tables", "jobs_job, jobs_recruiteraccount", ""),
    ("recruiter-applicants", "Quản lý hồ sơ ứng viên", "Nhà tuyển dụng", "derived", "jobs_application, accounts_profile, accounts_user", "Hồ sơ ứng tuyển và CV được liên kết qua đơn ứng tuyển."),
    ("recruiter-qualified-candidates", "Quản lý danh sách ứng viên đạt", "Nhà tuyển dụng", "tables", "jobs_qualifiedcandidate, jobs_application, jobs_job, accounts_user", "Danh sách ứng viên đạt được lưu riêng; mỗi dòng liên kết với đơn ứng tuyển, tin tuyển dụng và nhà tuyển dụng."),
    ("recruiter-interviews", "Lên lịch hẹn phỏng vấn", "Nhà tuyển dụng", "tables", "jobs_application", "Thông tin lịch hẹn lưu tại trường interview_details."),
    ("recruiter-chat-candidate", "Chat với ứng viên", "Nhà tuyển dụng", "tables", "jobs_jobchatmessage", ""),
    ("recruiter-contact-admin", "Phản hồi / hỗ trợ Admin", "Nhà tuyển dụng", "tables", "jobs_contactmessage", ""),
    ("recruiter-package-costs", "Thống kê kinh phí mua gói đăng tin", "Nhà tuyển dụng", "derived", "jobs_packagetransaction, jobs_subscriptionpackage", "Số liệu được tổng hợp từ giao dịch mua gói."),
    ("admin-login", "Đăng nhập Admin", "Admin", "tables", "accounts_user, auth_group, auth_permission, django_session", "Quyền truy cập trang quản trị dựa trên tài khoản staff/superuser."),
    ("admin-users-permissions", "Quản lý tài khoản và phân quyền", "Admin", "tables", "accounts_user, auth_group, auth_permission, accounts_user_groups, accounts_user_user_permissions, auth_group_permissions", "Vai trò ứng viên/nhà tuyển dụng nằm trong accounts_user; quyền Django dùng các bảng auth."),
    ("admin-companies", "Quản lý công ty tuyển dụng", "Admin", "derived", "jobs_companyprofile, accounts_user", "Thông tin công ty và trạng thái duyệt."),
    ("admin-statistics", "Quản lý thống kê", "Admin", "derived", "accounts_user, jobs_job, jobs_application, jobs_packagetransaction", "Thống kê được tổng hợp từ các bảng nghiệp vụ."),
    ("admin-support", "Hỗ trợ", "Admin", "tables", "jobs_contactmessage", ""),
]


def seed_system_features(apps, schema_editor):
    SystemFeature = apps.get_model("jobs", "SystemFeature")
    SystemFeature.objects.using(schema_editor.connection.alias).bulk_create(
        [
            SystemFeature(
                code=code,
                name=name,
                actor=actor,
                storage_status=storage_status,
                related_tables=related_tables,
                notes=notes,
            )
            for code, name, actor, storage_status, related_tables, notes in FEATURES
        ]
    )


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0029_notification_application"),
    ]

    operations = [
        migrations.CreateModel(
            name="SystemFeature",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(max_length=100, unique=True, verbose_name="Mã chức năng")),
                ("name", models.CharField(max_length=200, verbose_name="Tên chức năng")),
                ("actor", models.CharField(max_length=50, verbose_name="Vai trò")),
                ("storage_status", models.CharField(
                    choices=[
                        ("tables", "Có bảng dữ liệu"),
                        ("derived", "Tổng hợp từ bảng hiện có"),
                        ("static", "Nội dung tĩnh, không có bảng riêng"),
                    ],
                    max_length=20,
                    verbose_name="Trạng thái dữ liệu",
                )),
                ("related_tables", models.TextField(
                    blank=True,
                    help_text="Tên bảng MySQL, phân cách bằng dấu phẩy.",
                    verbose_name="Bảng dữ liệu liên quan",
                )),
                ("notes", models.TextField(blank=True, verbose_name="Ghi chú")),
            ],
            options={
                "verbose_name": "Chức năng hệ thống",
                "verbose_name_plural": "Danh mục chức năng hệ thống",
                "ordering": ("actor", "code"),
            },
        ),
        migrations.RunPython(seed_system_features, migrations.RunPython.noop),
    ]
