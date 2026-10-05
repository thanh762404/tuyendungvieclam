from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0021_job_major_required_job_skills_required'),
    ]

    operations = [
        migrations.AddField(
            model_name='job',
            name='max_hires',
            field=models.PositiveIntegerField(default=5, verbose_name='Số người tối đa được nhận'),
        ),
        migrations.AlterField(
            model_name='application',
            name='status',
            field=models.CharField(
                choices=[
                    ('Pending', 'Đang chờ duyệt'),
                    ('Approved', 'Đã duyệt / Phỏng vấn'),
                    ('InterviewPassed', 'Đạt phỏng vấn'),
                    ('Trial', 'Đang thử việc'),
                    ('Hired', 'Đã nhận / Đang đi làm'),
                    ('Rejected', 'Từ chối'),
                ],
                default='Pending',
                max_length=50,
                verbose_name='Trạng thái',
            ),
        ),
    ]