import json
import os
import tempfile
from importlib import import_module
from io import StringIO
from datetime import timedelta
from unittest.mock import patch

from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection
from django.http import Http404, HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from accounts.models import Profile, User
from jobs.forms import JobForm
from jobs.models import (
    Application,
    CompanyProfile,
    Job,
    JobChatMessage,
    Notification,
    PackageTransaction,
    QualifiedCandidate,
    RecruiterAccount,
    SubscriptionPackage,
    SystemFeature,
)
from jobs.services import send_interview_reminder_email
from jobs.views_candidate import (
    apply_job,
    candidate_applications,
    update_application_status,
)
from jobs.views_chat import (
    ask_gemini,
    get_job_chat_unread_count,
    send_job_chat_message,
)
from jobs.views_home import home_view
from jobs.views_admin import admin_approve_recruiter, admin_manage_jobs
from jobs.views_recruiter import (
    all_approved_candidates_view,
    buy_package_view,
    job_clone,
    job_create,
    job_achieved_candidates_view,
    mark_job_chat_read,
    recruiter_profile_view,
    recruiter_job_list,
)


class SystemFeatureCatalogTests(TestCase):
    def test_feature_catalog_is_seeded_for_all_roles(self):
        self.assertEqual(SystemFeature.objects.count(), 25)
        self.assertSetEqual(
            set(SystemFeature.objects.values_list("actor", flat=True).distinct()),
            {"Ứng viên", "Nhà tuyển dụng", "Admin"},
        )

    def test_static_news_feature_is_marked_as_having_no_database_table(self):
        feature = SystemFeature.objects.get(code="candidate-news")

        self.assertEqual(feature.storage_status, "static")
        self.assertEqual(feature.related_tables, "")


class JobChatMessageDisplayNameTests(TestCase):
    def test_sender_and_receiver_names_are_exposed(self):
        recruiter = User.objects.create_user(
            username="recruiter01",
            email="recruiter@example.com",
            password="123456",
            is_recruiter=True,
        )
        candidate = User.objects.create_user(
            username="candidate01",
            email="candidate@example.com",
            password="123456",
            is_candidate=True,
        )
        job = Job.objects.create(
            title="Python Developer",
            location="Hà Nội",
            salary="20-30 triệu",
            job_type="Full-time",
            description="Mô tả",
            requirements="Yêu cầu",
            recruiter=recruiter,
        )
        message = JobChatMessage.objects.create(
            job=job,
            sender=recruiter,
            receiver=candidate,
            message="Xin chào ứng viên",
        )

        self.assertEqual(message.sender_name, "recruiter01")
        self.assertEqual(message.receiver_name, "candidate01")


class CandidateJobRecommendationTests(TestCase):
    def setUp(self):
        recruiter = User.objects.create_user(
            username='recruiter',
            email='candidate-recommendation-recruiter@example.com',
            password='test-password',
            is_recruiter=True,
        )
        self.candidate = User.objects.create_user(
            username='candidate',
            email='candidate-recommendation-candidate@example.com',
            password='test-password',
            is_candidate=True,
        )
        self.profile = Profile.objects.create(
            user=self.candidate,
            major='Công nghệ thông tin',
            skills='Python',
        )
        self.request_factory = RequestFactory()
        self.matching_job = self.create_job(
            recruiter, 'Python Developer', 'Công nghệ thông tin', 'Python'
        )
        self.wrong_major_job = self.create_job(
            recruiter, 'Python Designer', 'Thiết kế đồ họa', 'Python'
        )
        self.wrong_skill_job = self.create_job(
            recruiter, 'Java Developer', 'Công nghệ thông tin', 'Java'
        )

    def create_job(self, recruiter, title, major, skills, description=None):
        return Job.objects.create(
            title=title,
            location='Hà Nội',
            salary='20 triệu',
            job_type='Full-time',
            description=description or f'Yêu cầu kỹ năng {skills}',
            requirements=f'Kinh nghiệm {skills}',
            major_required=major,
            skills_required=skills,
            recruiter=recruiter,
            status='Approved',
        )

    def get_home_context(self):
        request = self.request_factory.get('/')
        request.user = self.candidate
        with patch('jobs.views_home.render', return_value=HttpResponse()) as render:
            response = home_view(request)
        return response, render.call_args.args[2]

    def test_registered_major_and_skill_only_recommend_exact_match(self):
        response, context = self.get_home_context()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(context['suggested_jobs']),
            [self.matching_job],
        )

    def test_single_selected_skill_suggests_every_job_requiring_that_skill(self):
        self.profile.skills = 'MySQL'
        self.profile.save()
        mysql_python_job = self.create_job(
            self.matching_job.recruiter,
            'MySQL Python Developer',
            'Công nghệ thông tin',
            'MySQL, Python',
        )
        mysql_django_job = self.create_job(
            self.matching_job.recruiter,
            'MySQL Django Developer',
            'Công nghệ thông tin',
            'MySQL, Django',
        )

        _, context = self.get_home_context()

        self.assertEqual(
            set(context['suggested_jobs']),
            {mysql_python_job, mysql_django_job},
        )

    def test_expired_jobs_are_returned_separately_from_active_jobs(self):
        expired_job = self.create_job(
            self.matching_job.recruiter,
            'Expired Python Developer',
            'Công nghệ thông tin',
            'Python',
        )
        expired_job.expires_at = timezone.now() - timedelta(days=1)
        expired_job.save(update_fields=['expires_at'])

        _, context = self.get_home_context()

        self.assertIn(expired_job, context['expired_jobs'])
        self.assertNotIn(expired_job, context['jobs'])
        self.assertEqual(context['total_expired_jobs'], 1)


class JobMajorSkillValidationTests(TestCase):
    def job_form_data(self, major, skills):
        return {
            'title': 'Nhân viên tuyển dụng',
            'company_name': 'Công ty mẫu',
            'major_required': major,
            'skills_required': skills,
            'max_hires': 5,
            'location': 'Hà Nội',
            'salary': '15-20 triệu',
            'job_type': 'Full-time',
            'description': 'Mô tả công việc',
            'requirements': 'Yêu cầu ứng viên',
            'expires_at': '',
        }

    def test_job_form_accepts_multiple_skills_for_selected_major(self):
        form = JobForm(data=self.job_form_data('Công nghệ thông tin', 'Python, MySQL'))

        self.assertTrue(form.is_valid(), form.errors)

    def test_job_form_rejects_skills_from_another_major(self):
        form = JobForm(data=self.job_form_data('Logistics', 'Python'))

        self.assertFalse(form.is_valid())
        self.assertIn('skills_required', form.errors)


@override_settings(EMAIL_HOST_PASSWORD='test-app-password')
class JobHiringCapacityTests(TestCase):
    def setUp(self):
        self.recruiter = User.objects.create_user(
            username='recruiter', password='test-password', is_recruiter=True
        )
        self.job = Job.objects.create(
            title='Nhân viên kinh doanh',
            location='Hà Nội',
            salary='15 triệu',
            job_type='Full-time',
            description='Mô tả công việc',
            requirements='Yêu cầu ứng viên',
            major_required='Quản trị kinh doanh',
            skills_required='Phân tích kinh doanh',
            max_hires=1,
            recruiter=self.recruiter,
            status='Approved',
        )
        self.request_factory = RequestFactory()

    def create_application(self, username, status='Approved'):
        candidate = User.objects.create_user(
            username=username,
            email=f'{username}@example.com',
            password='test-password',
            is_candidate=True,
        )
        return Application.objects.create(
            job=self.job,
            candidate=candidate,
            cv_file=f'applications_cvs/{username}.pdf',
            status=status,
        )

    def test_job_table_keeps_company_name_next_to_recruiter_foreign_key(self):
        CompanyProfile.objects.create(
            user=self.recruiter,
            company_name='Công ty Minh An',
        )

        self.job.refresh_from_db()

        self.assertEqual(self.job.company_name, 'Công ty Minh An')
        self.assertEqual(self.job.recruiter_name, 'Công ty Minh An')

    def test_recruiter_profile_renders_and_saves_company_address(self):
        company_profile = CompanyProfile.objects.create(
            user=self.recruiter,
            company_name='Công ty Minh An',
            address='Địa chỉ cũ',
        )
        self.client.force_login(self.recruiter)

        response = self.client.get('/recruiter/profile/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="id_address"')
        self.assertContains(response, 'name="address"')
        self.assertContains(response, 'value="Địa chỉ cũ"')

        response = self.client.post(
            '/recruiter/profile/',
            {
                'company_name': 'Công ty Minh An',
                'phone': '',
                'address': 'Địa chỉ mới',
                'website': '',
                'description': '',
            },
        )

        company_profile.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(company_profile.address, 'Địa chỉ mới')

    def update_status(
        self,
        application,
        status,
        interview_date='',
        interview_time='',
        interview_period='',
    ):
        post_data = {
            'status': status,
            'interview_date': interview_date,
            'interview_time': interview_time,
            'interview_note': '',
        }
        if status == 'Approved' and interview_time:
            hour, minute = interview_time.split(':', 1)
            hour_24 = int(hour)
            post_data.update(
                {
                    'interview_hour': f'{hour_24 % 12 or 12:02d}',
                    'interview_minute': minute,
                    'interview_period': 'PM' if hour_24 >= 12 else 'AM',
                }
            )
        if interview_period:
            post_data['interview_period'] = interview_period
        request = self.request_factory.post(
            f'/application/{application.pk}/update/',
            post_data,
        )
        request.user = self.recruiter
        request.session = {}
        request._messages = FallbackStorage(request)
        with patch('jobs.views_candidate.redirect', return_value=HttpResponse()), patch(
            'jobs.views_candidate.render', return_value=HttpResponse()
        ):
            return update_application_status(request, application.pk)

    def update_schedule(self, application, interview_date, interview_time, period):
        post_data = {
            'action': 'update_schedule',
            'status': application.status,
            'interview_date': interview_date,
        }
        if application.status == 'Approved':
            hour, minute = interview_time.split(':', 1)
            post_data.update(
                {
                    'interview_hour': hour,
                    'interview_minute': minute,
                    'interview_period': period,
                }
            )
        else:
            post_data['interview_time'] = interview_time
        request = self.request_factory.post(
            f'/application/{application.pk}/update/',
            post_data,
        )
        request.user = self.recruiter
        request.session = {}
        request._messages = FallbackStorage(request)
        with patch('jobs.views_candidate.redirect', return_value=HttpResponse()), patch(
            'jobs.views_candidate.render', return_value=HttpResponse()
        ):
            return update_application_status(request, application.pk)

    def test_interview_reminder_sends_gmail_once_within_24_hours(self):
        application = self.create_application('reminder-candidate', status='Approved')
        application.candidate.email = 'candidate@example.com'
        application.candidate.save(update_fields=['email'])
        application.candidate.first_name = 'Nguyen'
        application.candidate.last_name = 'Van A'
        application.candidate.save(update_fields=['first_name', 'last_name'])
        interview_at = timezone.now() + timedelta(hours=12)
        application.interview_details = (
            f"Ngày: {interview_at.strftime('%Y-%m-%d')}\n"
            f"Giờ: {interview_at.strftime('%H:%M')}"
        )
        application.save(update_fields=['interview_details'])

        with patch('jobs.services.send_mail', return_value=1) as send_mail:
            self.assertTrue(send_interview_reminder_email(application))
            self.assertFalse(send_interview_reminder_email(application))

        application.refresh_from_db()
        self.assertTrue(application.reminder_sent)
        send_mail.assert_called_once()
        self.assertEqual(send_mail.call_args.args[3], ['candidate@example.com'])
        self.assertIn('Nguyen Van A', send_mail.call_args.args[1])
        self.assertIn('trong vòng 24 giờ', send_mail.call_args.args[1])

    def test_interview_reminder_reports_missing_gmail_app_password(self):
        application = self.create_application('missing-password-candidate')
        interview_at = timezone.now() + timedelta(hours=12)
        application.interview_details = (
            f"Ngày: {interview_at.strftime('%Y-%m-%d')}\n"
            f"Giờ: {interview_at.strftime('%H:%M')}"
        )
        application.save(update_fields=['interview_details'])

        with override_settings(EMAIL_HOST_PASSWORD=''):
            with self.assertRaisesRegex(RuntimeError, 'EMAIL_HOST_PASSWORD'):
                send_interview_reminder_email(application)

    def test_scheduled_command_sends_only_reminders_due_within_24_hours(self):
        due_application = self.create_application(
            'due-reminder-candidate',
            status='Approved',
        )
        due_application.candidate.email = 'due@example.com'
        due_application.candidate.save(update_fields=['email'])
        due_time = timezone.now() + timedelta(hours=23)
        due_application.interview_details = (
            f"Ngày: {due_time.strftime('%Y-%m-%d')}\n"
            f"Giờ: {due_time.strftime('%H:%M')}"
        )
        due_application.save(update_fields=['interview_details'])

        later_application = self.create_application(
            'later-reminder-candidate',
            status='Approved',
        )
        later_application.candidate.email = 'later@example.com'
        later_application.candidate.save(update_fields=['email'])
        later_time = timezone.now() + timedelta(hours=25)
        later_application.interview_details = (
            f"Ngày: {later_time.strftime('%Y-%m-%d')}\n"
            f"Giờ: {later_time.strftime('%H:%M')}"
        )
        later_application.save(update_fields=['interview_details'])

        with patch('jobs.services.send_mail', return_value=1) as send_mail:
            call_command('send_interview_reminders', stdout=StringIO())

        due_application.refresh_from_db()
        later_application.refresh_from_db()
        self.assertTrue(due_application.reminder_sent)
        self.assertFalse(later_application.reminder_sent)
        send_mail.assert_called_once()
        self.assertEqual(send_mail.call_args.args[3], ['due@example.com'])

    def test_trial_status_emails_work_schedule_and_notifies_candidate(self):
        application = self.create_application('trial-notice-candidate', status='Approved')
        application.candidate.email = 'candidate@example.com'
        application.candidate.save(update_fields=['email'])
        interview_date = (timezone.now().date() + timedelta(days=2)).isoformat()

        with patch('jobs.services.send_mail', return_value=1) as send_mail:
            response = self.update_status(
                application,
                'Trial',
                interview_date=interview_date,
                interview_time='09:00',
            )

        application.refresh_from_db()
        notification = JobChatMessage.objects.get(
            receiver=application.candidate,
            is_application_update=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(application.status, 'Trial')
        self.assertIn('Lịch bắt đầu thử việc/đi làm', notification.message)
        self.assertIn(interview_date, notification.message)
        self.assertEqual(send_mail.call_args.args[3], ['candidate@example.com'])
        self.assertIn('Đang thử việc', send_mail.call_args.args[1])
        self.assertIn('Lịch bắt đầu thử việc/đi làm', send_mail.call_args.args[1])
        self.assertIn(interview_date, send_mail.call_args.args[1])

    def test_updating_schedule_without_changing_status_sends_email_and_notification(self):
        application = self.create_application('schedule-update-candidate', status='Approved')
        application.candidate.email = 'candidate@example.com'
        application.candidate.save(update_fields=['email'])
        application.interview_details = 'Ngày: 2026-10-05\nGiờ: 09:00'
        application.save(update_fields=['interview_details'])
        interview_date = (timezone.now().date() + timedelta(days=3)).isoformat()

        with patch('jobs.services.send_mail', return_value=1) as send_mail:
            response = self.update_status(
                application,
                'Approved',
                interview_date=interview_date,
                interview_time='10:30',
            )

        application.refresh_from_db()
        notification = JobChatMessage.objects.get(
            receiver=application.candidate,
            is_application_update=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(application.status, 'Approved')
        self.assertIn(interview_date, application.interview_details)
        self.assertIn('đã được nhà tuyển dụng cập nhật', notification.message)
        send_mail.assert_called_once()
        self.assertIn(interview_date, send_mail.call_args.args[1])

    def test_schedule_only_update_uses_24_hour_values_and_preserves_status_and_notes(self):
        application = self.create_application('schedule-only-candidate', status='Hired')
        application.interview_details = (
            'Ngày: 2026-10-05\n'
            'Giờ: 09:00\n'
            'Địa điểm: Văn phòng công ty\n'
            'Ghi chú: Mang theo hồ sơ'
        )
        application.save(update_fields=['interview_details'])
        interview_date = (timezone.now().date() + timedelta(days=3)).isoformat()

        with patch('jobs.services.send_mail', return_value=1) as send_mail:
            response = self.update_schedule(
                application,
                interview_date=interview_date,
                interview_time='14:30',
                period='',
            )

        application.refresh_from_db()
        notification = JobChatMessage.objects.get(
            receiver=application.candidate,
            is_application_update=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(application.status, 'Hired')
        self.assertIn(f'Ngày: {interview_date}', application.interview_details)
        self.assertIn('Giờ: 14:30', application.interview_details)
        self.assertIn('Địa điểm: Văn phòng công ty', application.interview_details)
        self.assertIn('Ghi chú: Mang theo hồ sơ', application.interview_details)
        self.assertIn('14:30', notification.message)
        send_mail.assert_called_once()

    def test_approved_interview_picker_converts_midnight_and_noon(self):
        interview_date = (timezone.now().date() + timedelta(days=3)).isoformat()
        for username, hour, period, expected_time in (
            ('midnight-candidate', '12:15', 'AM', '00:15'),
            ('noon-candidate', '12:15', 'PM', '12:15'),
        ):
            with self.subTest(period=period):
                application = self.create_application(username, status='Approved')
                response = self.update_schedule(
                    application,
                    interview_date=interview_date,
                    interview_time=hour,
                    period=period,
                )

                application.refresh_from_db()
                self.assertEqual(response.status_code, 200)
                self.assertEqual(application.status, 'Approved')
                self.assertIn(
                    f'Giờ: {expected_time}',
                    application.interview_details,
                )

    def test_database_views_expose_names_and_active_expired_job_counts(self):
        candidate_application = self.create_application(
            'readable-view-candidate',
            status='Trial',
        )
        CompanyProfile.objects.create(
            user=self.recruiter,
            company_name='Công ty Minh An',
        )
        expired_job = Job.objects.create(
            title='Công việc đã hết hạn',
            location='Đà Nẵng',
            salary='12 triệu',
            job_type='Full-time',
            description='Mô tả',
            requirements='Yêu cầu',
            recruiter=self.recruiter,
            expires_at=timezone.now() - timedelta(days=1),
        )

        migration = import_module(
            'jobs.migrations.0033_qualifiedcandidate_readable_view'
        )
        schema_editor = connection.schema_editor()
        migration.create_readable_view(None, schema_editor)

        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT candidate_name, recruiter_name, company_name, job_title '
                'FROM jobs_qualifiedcandidate'
            )
            table_names = cursor.fetchone()
            cursor.execute(
                'SELECT candidate_name, recruiter_name, company_name, job_title, status '
                'FROM jobs_qualifiedcandidate_readable'
            )
            readable_row = cursor.fetchone()
            readable_columns = [column[0] for column in cursor.description]
            cursor.execute(
                'SELECT job_title, expiration_status '
                'FROM jobs_job_expiration_status WHERE job_title = %s',
                [expired_job.title],
            )
            expired_row = cursor.fetchone()
            cursor.execute('SELECT total_jobs, active_jobs, expired_jobs FROM jobs_job_expiration_counts')
            job_counts = cursor.fetchone()

        self.assertEqual(
            readable_row,
            (
                candidate_application.candidate.display_name,
                'Công ty Minh An',
                'Công ty Minh An',
                self.job.title,
                'Đang thử việc',
            ),
        )
        self.assertEqual(
            table_names,
            (
                candidate_application.candidate.display_name,
                'Công ty Minh An',
                'Công ty Minh An',
                self.job.title,
            ),
        )
        self.assertFalse(any(column.endswith('_id') for column in readable_columns))
        self.assertEqual(expired_row, (expired_job.title, 'Hết hạn'))
        self.assertEqual(job_counts, (2, 1, 1))

    def test_qualified_candidates_link_to_the_application_cv(self):
        application = self.create_application('qualified-cv-candidate')
        application.cv_file = 'applications_cvs/qualified-cv-candidate.pdf'

        rendered = render_to_string(
            'jobs/all_approved_candidates.html',
            {'approved_list': [application]},
        )

        self.assertIn(
            '/media/applications_cvs/qualified-cv-candidate.pdf',
            rendered,
        )
        self.assertIn('Xem CV', rendered)

    def test_applications_are_not_limited_by_hiring_capacity(self):
        candidate = User.objects.create_user(
            username='applicant', password='test-password', is_candidate=True
        )
        request = self.request_factory.post(
            f'/jobs/{self.job.pk}/apply/',
            {
                'cover_letter': '',
                'cv_file': SimpleUploadedFile('candidate.pdf', b'candidate CV'),
            },
        )
        request.user = candidate

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                with patch('jobs.views_candidate.render', return_value=HttpResponse()):
                    response = apply_job(request, self.job.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.job.applications.count(), 1)

    def test_quota_blocks_an_extra_trial_hire_but_allows_interview_pass(self):
        first_application = self.create_application('first-candidate')
        second_application = self.create_application('second-candidate')

        first_response = self.update_status(first_application, 'InterviewPassed')
        self.assertEqual(first_response.status_code, 200)
        first_application.refresh_from_db()
        self.assertEqual(first_application.status, 'InterviewPassed')

        blocked_response = self.update_status(second_application, 'InterviewPassed')
        self.assertEqual(blocked_response.status_code, 200)
        second_application.refresh_from_db()
        self.assertEqual(second_application.status, 'Approved')

    def test_promoting_trial_to_hired_keeps_the_same_slot(self):
        application = self.create_application('first-candidate', status='Trial')

        response = self.update_status(application, 'Hired')

        self.assertEqual(response.status_code, 200)
        application.refresh_from_db()
        self.assertEqual(application.status, 'Hired')
        self.assertEqual(
            self.job.applications.filter(status__in=('InterviewPassed', 'Trial', 'Hired')).count(),
            1,
        )

    def test_recruiter_job_list_shows_occupied_slot_count(self):
        self.create_application('passed-candidate', status='InterviewPassed')
        self.create_application('trial-candidate', status='Trial')
        self.create_application('hired-candidate', status='Hired')
        request = self.request_factory.get('/recruiter/jobs/')
        request.user = self.recruiter

        with patch('jobs.views_recruiter.render', return_value=HttpResponse()) as render:
            response = recruiter_job_list(request)

        context = render.call_args.args[2]
        displayed_job = next(job for job in context['jobs'] if job.pk == self.job.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(displayed_job.hired_count, 3)
        self.assertFalse(hasattr(displayed_job, 'hiring_applications'))

    def test_recruiter_chat_badges_count_only_unread_candidate_messages(self):
        candidate = User.objects.create_user(
            username='chat-candidate',
            email='chat-candidate@example.com',
            password='test-password',
            is_candidate=True,
        )
        JobChatMessage.objects.bulk_create(
            [
                JobChatMessage(
                    job=self.job,
                    sender=candidate,
                    receiver=self.recruiter,
                    message=f'Câu hỏi {index}',
                )
                for index in range(3)
            ]
            + [
                JobChatMessage(
                    job=self.job,
                    sender=self.recruiter,
                    receiver=candidate,
                    message=f'Trả lời AI {index}',
                )
                for index in range(3)
            ]
        )
        request = self.request_factory.get('/recruiter/jobs/')
        request.user = self.recruiter

        with patch('jobs.views_recruiter.render', return_value=HttpResponse()) as render:
            response = recruiter_job_list(request)

        context = render.call_args.args[2]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(context['total_unread'], 3)
        self.assertEqual(context['chat_conversations'][0]['unread_count'], 3)

    def test_job_achieved_candidates_shows_only_that_jobs_pipeline(self):
        self.create_application('passed-candidate', status='InterviewPassed')
        self.create_application('trial-candidate', status='Trial')
        self.create_application('pending-candidate', status='Pending')
        self.assertEqual(QualifiedCandidate.objects.count(), 2)
        request = self.request_factory.get(f'/recruiter/jobs/{self.job.pk}/achieved-candidates/')
        request.user = self.recruiter

        with patch('jobs.views_recruiter.render', return_value=HttpResponse()) as render:
            response = job_achieved_candidates_view(request, self.job.pk)

        context = render.call_args.args[2]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(context['job'], self.job)
        self.assertEqual(
            {application.candidate.username for application in context['approved_list']},
            {'passed-candidate', 'trial-candidate'},
        )

    def test_qualified_candidate_rows_are_owned_by_their_recruiter_and_job(self):
        application = self.create_application(
            'owned-qualified-candidate',
            status='InterviewPassed',
        )
        other_recruiter = User.objects.create_user(
            username='other-recruiter',
            email='other-recruiter@example.com',
            password='test-password',
            is_recruiter=True,
        )
        other_job = Job.objects.create(
            title='Nhân viên kế toán',
            location='Đà Nẵng',
            salary='12 triệu',
            job_type='Full-time',
            description='Mô tả công việc',
            requirements='Yêu cầu ứng viên',
            recruiter=other_recruiter,
        )
        other_candidate = User.objects.create_user(
            username='other-qualified-candidate',
            email='other-qualified-candidate@example.com',
            password='test-password',
            is_candidate=True,
        )
        other_application = Application.objects.create(
            job=other_job,
            candidate=other_candidate,
            cv_file='applications_cvs/other-qualified-candidate.pdf',
            status='Trial',
        )

        qualified_rows = QualifiedCandidate.objects.order_by("recruiter_id")
        self.assertEqual(qualified_rows.count(), 2)
        self.assertEqual(
            (
                qualified_rows[0].candidate_id,
                qualified_rows[0].job_id,
                qualified_rows[0].recruiter_id,
                qualified_rows[0].application_id,
            ),
            (
                application.candidate_id,
                self.job.pk,
                self.recruiter.pk,
                application.pk,
            ),
        )
        self.assertEqual(
            (
                qualified_rows[1].candidate_id,
                qualified_rows[1].job_id,
                qualified_rows[1].recruiter_id,
                qualified_rows[1].application_id,
            ),
            (
                other_application.candidate_id,
                other_job.pk,
                other_recruiter.pk,
                other_application.pk,
            ),
        )

        request = self.request_factory.get('/recruiter/all-approved-candidates/')
        request.user = self.recruiter
        with patch('jobs.views_recruiter.render', return_value=HttpResponse()) as render:
            response = all_approved_candidates_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row.candidate.username for row in render.call_args.args[2]['approved_list']],
            [application.candidate.username],
        )

    def test_job_achieved_candidates_rejects_another_recruiters_job(self):
        other_recruiter = User.objects.create_user(
            username='other-recruiter', password='test-password', is_recruiter=True
        )
        request = self.request_factory.get('/recruiter/jobs/')
        request.user = other_recruiter

        with self.assertRaises(Http404):
            job_achieved_candidates_view(request, self.job.pk)


class JobChatAssistantTests(TestCase):
    def setUp(self):
        self.recruiter = User.objects.create_user(
            username='recruiter',
            email='recruiter@example.com',
            password='test-password',
            is_recruiter=True,
        )
        CompanyProfile.objects.create(
            user=self.recruiter,
            company_name='Công ty mẫu',
            address='123 Đường Nguyễn Huệ, TP. Hồ Chí Minh',
        )
        self.candidate = User.objects.create_user(
            username='candidate',
            email='candidate@example.com',
            password='test-password',
            is_candidate=True,
        )
        self.job = Job.objects.create(
            title='Python Backend Developer',
            location='Hà Nội',
            salary='20 triệu',
            job_type='Full-time',
            description='Phát triển API tuyển dụng.',
            requirements='Biết Python và Django.',
            major_required='Công nghệ thông tin',
            skills_required='Python, Django',
            recruiter=self.recruiter,
            status='Approved',
        )
        self.request_factory = RequestFactory()

    def test_gemini_call_has_short_timeout_and_no_retries(self):
        response = type('GeminiResponse', (), {'text': 'Trả lời nhanh'})()
        client = type(
            'GeminiClient',
            (),
            {
                'models': type(
                    'Models',
                    (),
                    {'generate_content': lambda self, **kwargs: response},
                )(),
                'close': lambda self: None,
            },
        )()
        with patch.dict(os.environ, {'GOOGLE_API_KEY': 'test-key'}), patch(
            'jobs.views_chat.genai.Client', return_value=client
        ) as create_client:
            result = ask_gemini('Trả lời ngắn gọn', 'Câu hỏi tuyển dụng')

        self.assertEqual(result, 'Trả lời nhanh')
        http_options = create_client.call_args.kwargs['http_options']
        self.assertEqual(http_options.timeout, 8000)
        self.assertEqual(http_options.retry_options.attempts, 1)

    def test_candidate_gets_instant_answer_from_job_listing(self):
        self.client.force_login(self.candidate)

        with patch('jobs.views_chat.ask_gemini') as ask_gemini:
            response = self.client.post(
                f'/jobs/{self.job.pk}/chat/send/',
                {'message': 'Mức lương vị trí này là bao nhiêu?'},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        self.assertIn('20 triệu', response.json()['reply'])
        ask_gemini.assert_not_called()
        messages = list(
            JobChatMessage.objects.filter(job=self.job).order_by('created_at', 'pk')
        )
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].sender, self.candidate)
        self.assertEqual(messages[1].sender, self.recruiter)

    def test_general_question_uses_fast_ai_and_reply_is_saved(self):
        self.client.force_login(self.candidate)

        with patch(
            'jobs.views_chat.ask_gemini',
            return_value='{"related": true, "answer": "AI trả lời về công việc."}',
        ) as ask_gemini:
            response = self.client.post(
                f'/jobs/{self.job.pk}/chat/send/',
                {'message': 'Công ty có những phúc lợi nào?'},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['reply'], 'AI trả lời về công việc.')
        ask_gemini.assert_called_once()
        self.assertTrue(
            JobChatMessage.objects.filter(
                job=self.job,
                sender=self.recruiter,
                receiver=self.candidate,
                message='AI trả lời về công việc.',
            ).exists()
        )

    def test_off_topic_question_gets_polite_scope_redirect(self):
        self.client.force_login(self.candidate)

        with patch('jobs.views_chat.ask_gemini') as ask_gemini:
            response = self.client.post(
                f'/jobs/{self.job.pk}/chat/send/',
                {'message': 'Bạn ăn cơm chưa?'},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn('chỉ hỗ trợ các câu hỏi', response.json()['reply'])
        ask_gemini.assert_not_called()

    def test_ai_can_reject_off_topic_question_with_job_related_keyword(self):
        self.client.force_login(self.candidate)

        with patch(
            'jobs.views_chat.ask_gemini',
            return_value='{"related": false, "answer": ""}',
        ) as ask_gemini:
            response = self.client.post(
                f'/jobs/{self.job.pk}/chat/send/',
                {'message': 'Lương của cầu thủ Messi là bao nhiêu?'},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn('chỉ hỗ trợ các câu hỏi', response.json()['reply'])
        ask_gemini.assert_called_once()
        ask_gemini.assert_called_once()

    def test_candidate_chat_history_is_oldest_to_newest(self):
        older_question = JobChatMessage.objects.create(
            job=self.job,
            sender=self.candidate,
            receiver=self.recruiter,
            message='Câu hỏi trước',
        )
        older_reply = JobChatMessage.objects.create(
            job=self.job,
            sender=self.recruiter,
            receiver=self.candidate,
            message='Câu trả lời trước',
        )
        newer_question = JobChatMessage.objects.create(
            job=self.job,
            sender=self.candidate,
            receiver=self.recruiter,
            message='Câu hỏi mới nhất',
        )
        newer_reply = JobChatMessage.objects.create(
            job=self.job,
            sender=self.recruiter,
            receiver=self.candidate,
            message='Câu trả lời mới nhất',
        )
        self.client.force_login(self.candidate)

        response = self.client.get(f'/jobs/{self.job.pk}/chat/history/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [message['message'] for message in response.json()['messages']],
            [
                older_question.message,
                older_reply.message,
                newer_question.message,
                newer_reply.message,
            ],
        )
        self.assertEqual(
            response.json()['messages'][0]['created_at'],
            older_question.created_at.strftime('%d/%m/%Y %H:%M'),
        )
        self.assertIn('id', response.json()['messages'][0])

    def test_recruiter_can_delete_entire_chat_conversation_for_their_job(self):
        question = JobChatMessage.objects.create(
            job=self.job,
            sender=self.candidate,
            receiver=self.recruiter,
            message='Câu hỏi',
        )
        answer = JobChatMessage.objects.create(
            job=self.job,
            sender=self.recruiter,
            receiver=self.candidate,
            message='Câu trả lời',
        )
        application_update = JobChatMessage.objects.create(
            job=self.job,
            sender=self.recruiter,
            receiver=self.candidate,
            message='Cập nhật trạng thái hồ sơ',
            is_application_update=True,
        )
        self.client.force_login(self.recruiter)

        response = self.client.post(
            f'/jobs/{self.job.pk}/chat/{self.candidate.pk}/delete-conversation/'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        self.assertFalse(
            JobChatMessage.objects.filter(pk__in=[question.pk, answer.pk]).exists()
        )
        self.assertTrue(JobChatMessage.objects.filter(pk=application_update.pk).exists())

    def test_recruiter_cannot_delete_another_recruiters_conversation(self):
        other_recruiter = User.objects.create_user(
            username='another-recruiter',
            email='another-recruiter@example.com',
            password='test-password',
            is_recruiter=True,
        )
        other_job = Job.objects.create(
            title='Other job',
            location='Đà Nẵng',
            salary='15 triệu',
            job_type='Full-time',
            description='Tin tuyển dụng khác.',
            requirements='Kinh nghiệm phù hợp.',
            recruiter=other_recruiter,
            status='Approved',
        )
        message = JobChatMessage.objects.create(
            job=other_job,
            sender=self.candidate,
            receiver=other_recruiter,
            message='Tin nhắn riêng',
        )
        self.client.force_login(self.recruiter)

        response = self.client.post(
            f'/jobs/{other_job.pk}/chat/{self.candidate.pk}/delete-conversation/'
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(JobChatMessage.objects.filter(pk=message.pk).exists())

    def test_submitting_application_notifies_the_job_recruiter(self):
        self.client.force_login(self.candidate)
        with tempfile.TemporaryDirectory() as media_root, override_settings(
            MEDIA_ROOT=media_root
        ):
            response = self.client.post(
                f'/jobs/{self.job.pk}/apply/',
                {
                    'cv_file': SimpleUploadedFile(
                        'resume.pdf', b'pdf-content', content_type='application/pdf'
                    ),
                    'cover_letter': 'Tôi muốn ứng tuyển.',
                },
            )

        notification = Notification.objects.get(recipient=self.recruiter)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(notification.title, 'Ứng viên mới ứng tuyển')
        self.assertEqual(notification.job_title, self.job.title)
        self.assertEqual(notification.application.job, self.job)
        self.assertIn(self.candidate.username, notification.message)

    def test_recruiter_notification_links_to_applicant_review_and_schedule(self):
        application = Application.objects.create(
            job=self.job,
            candidate=self.candidate,
            cv_file='applications_cvs/resume.pdf',
            cover_letter='Tôi muốn ứng tuyển.',
        )
        notification = Notification.objects.create(
            recipient=self.recruiter,
            title='Ứng viên mới ứng tuyển',
            message='Ứng viên vừa nộp hồ sơ.',
            application=application,
        )
        self.client.force_login(self.recruiter)

        response = self.client.get('/api/notifications/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['notifications'][0]['action_url'],
            f'/jobs/{self.job.pk}/applications/?application_id={application.pk}',
        )
        self.assertTrue(Notification.objects.filter(pk=notification.pk).exists())

    def test_legacy_recruiter_notification_links_to_matching_application(self):
        application = Application.objects.create(
            job=self.job,
            candidate=self.candidate,
            cv_file='applications_cvs/resume.pdf',
        )
        notification = Notification.objects.create(
            recipient=self.recruiter,
            title='Ứng viên mới ứng tuyển',
            message=f'{self.candidate.display_name} vừa nộp hồ sơ ứng tuyển vào tin tuyển dụng này.',
            job_title=self.job.title,
        )
        self.client.force_login(self.recruiter)

        response = self.client.get('/api/notifications/')
        item = next(
            item
            for item in response.json()['notifications']
            if item['id'] == notification.pk
        )

        self.assertEqual(
            item['action_url'],
            f'/jobs/{self.job.pk}/applications/?application_id={application.pk}',
        )

    def test_recruiter_can_only_read_and_delete_their_notifications(self):
        other_recruiter = User.objects.create_user(
            username='another-recruiter',
            email='another-recruiter@example.com',
            password='test-password',
            is_recruiter=True,
        )
        own_notification = Notification.objects.create(
            recipient=self.recruiter,
            title='Ứng viên mới ứng tuyển',
            message='Ứng viên mới đã nộp CV.',
            job_title=self.job.title,
        )
        other_notification = Notification.objects.create(
            recipient=other_recruiter,
            title='Thông báo riêng',
            message='Không được hiển thị cho nhà tuyển dụng khác.',
        )
        self.client.force_login(self.recruiter)

        response = self.client.get('/api/notifications/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item['id'] for item in response.json()['notifications']],
            [own_notification.pk],
        )
        response = self.client.post(
            '/api/notifications/delete/',
            {'notif_id': other_notification.pk},
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Notification.objects.filter(pk=own_notification.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=other_notification.pk).exists())

        response = self.client.post(
            '/api/notifications/delete/',
            {'notif_id': own_notification.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Notification.objects.filter(pk=own_notification.pk).exists())

        bulk_notifications = Notification.objects.bulk_create(
            [
                Notification(
                    recipient=self.recruiter,
                    title='Thông báo mới',
                    message='Thông báo cần xóa.',
                )
                for _ in range(2)
            ]
        )
        response = self.client.post('/api/notifications/delete-all/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            Notification.objects.filter(
                pk__in=[notification.pk for notification in bulk_notifications]
            ).exists()
        )
        self.assertTrue(Notification.objects.filter(pk=other_notification.pk).exists())

    def test_candidate_delete_all_only_removes_application_notifications(self):
        update = JobChatMessage.objects.create(
            job=self.job,
            sender=self.recruiter,
            receiver=self.candidate,
            message='Hồ sơ đã được cập nhật.',
            is_application_update=True,
        )
        chat_message = JobChatMessage.objects.create(
            job=self.job,
            sender=self.recruiter,
            receiver=self.candidate,
            message='Tin nhắn trao đổi.',
        )
        self.client.force_login(self.candidate)

        response = self.client.post(
            '/api/notifications/delete/',
            {'notif_id': update.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(JobChatMessage.objects.filter(pk=update.pk).exists())

        updates_to_clear = JobChatMessage.objects.bulk_create(
            [
                JobChatMessage(
                    job=self.job,
                    sender=self.recruiter,
                    receiver=self.candidate,
                    message='Thông báo cần xóa.',
                    is_application_update=True,
                )
                for _ in range(2)
            ]
        )
        response = self.client.post('/api/notifications/delete-all/')

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            JobChatMessage.objects.filter(
                pk__in=[notification.pk for notification in updates_to_clear]
            ).exists()
        )
        self.assertTrue(JobChatMessage.objects.filter(pk=chat_message.pk).exists())

    def create_application(self, username, status='Approved'):
        candidate = User.objects.create_user(
            username=username,
            email=f'{username}@example.com',
            password='test-password',
            is_candidate=True,
        )
        return Application.objects.create(
            job=self.job,
            candidate=candidate,
            cv_file=f'applications_cvs/{username}.pdf',
            status=status,
        )

    def update_status(
        self, application, status, interview_date='', interview_time='', interview_note=''
    ):
        request = self.request_factory.post(
            f'/application/{application.pk}/update/',
            {
                'status': status,
                'interview_date': interview_date,
                'interview_time': interview_time,
                'interview_note': interview_note,
            },
        )
        request.user = self.recruiter
        request.session = {}
        request._messages = FallbackStorage(request)
        with patch('jobs.views_candidate.redirect', return_value=HttpResponse()), patch(
            'jobs.views_candidate.render', return_value=HttpResponse()
        ):
            return update_application_status(request, application.pk)

    def update_schedule(self, application, interview_date, interview_time, period):
        post_data = {
            'action': 'update_schedule',
            'status': application.status,
            'interview_date': interview_date,
        }
        if application.status == 'Approved':
            hour, minute = interview_time.split(':', 1)
            hour_24 = int(hour)
            post_data.update(
                {
                    'interview_hour': f'{hour_24 % 12 or 12:02d}',
                    'interview_minute': minute,
                    'interview_period': period or ('PM' if hour_24 >= 12 else 'AM'),
                }
            )
        else:
            post_data['interview_time'] = interview_time
        request = self.request_factory.post(
            f'/application/{application.pk}/update/',
            post_data,
        )
        request.user = self.recruiter
        request.session = {}
        request._messages = FallbackStorage(request)
        with patch('jobs.views_candidate.redirect', return_value=HttpResponse()), patch(
            'jobs.views_candidate.render', return_value=HttpResponse()
        ):
            return update_application_status(request, application.pk)

    def test_candidate_unread_badge_clears_after_opening_chat(self):
        message = JobChatMessage.objects.create(
            job=self.job,
            sender=self.recruiter,
            receiver=self.candidate,
            message='Lịch phỏng vấn của bạn đã được xác nhận.',
        )
        unread_request = RequestFactory().get(f'/jobs/{self.job.pk}/chat/unread-count/')
        unread_request.user = self.candidate

        unread_response = get_job_chat_unread_count(unread_request, self.job.pk)

        self.assertEqual(json.loads(unread_response.content)['unread_count'], 1)

        mark_read_request = RequestFactory().post(f'/jobs/{self.job.pk}/chat/mark-read/')
        mark_read_request.user = self.candidate
        mark_response = mark_job_chat_read(mark_read_request, self.job.pk)

        self.assertEqual(mark_response.status_code, 200)
        message.refresh_from_db()
        self.assertTrue(message.is_read)
        self.assertEqual(
            json.loads(get_job_chat_unread_count(unread_request, self.job.pk).content)['unread_count'],
            0,
        )

    def test_approval_requires_interview_schedule_and_notifies_candidate(self):
        application = self.create_application('interview-candidate', status='Pending')

        missing_schedule_response = self.update_status(application, 'Approved')

        self.assertEqual(missing_schedule_response.status_code, 200)
        application.refresh_from_db()
        self.assertEqual(application.status, 'Pending')
        self.assertFalse(JobChatMessage.objects.filter(receiver=application.candidate).exists())

        interview_date = (timezone.now().date() + timedelta(days=2)).isoformat()
        response = self.update_status(
            application,
            'Approved',
            interview_date=interview_date,
            interview_time='14:30',
        )

        self.assertEqual(response.status_code, 200)
        application.refresh_from_db()
        notification = JobChatMessage.objects.get(receiver=application.candidate)
        self.assertEqual(application.status, 'Approved')
        self.assertIn(f'Ngày: {interview_date}', application.interview_details)
        self.assertIn('Giờ: 14:30', application.interview_details)
        self.assertIn('Đã duyệt / Phỏng vấn', notification.message)
        self.assertIn(interview_date, notification.message)

    def test_interview_location_comes_from_recruiter_profile_and_note_is_separate(self):
        application = self.create_application('location-candidate', status='Pending')
        interview_date = (timezone.now().date() + timedelta(days=2)).isoformat()

        response = self.update_status(
            application,
            'Approved',
            interview_date=interview_date,
            interview_time='14:30',
            interview_note='Mang theo CV\nĐịa điểm: liên hệ nhân sự nếu cần đổi lịch.',
        )

        self.assertEqual(response.status_code, 200)
        application.refresh_from_db()
        self.assertIn(
            'Địa điểm: 123 Đường Nguyễn Huệ, TP. Hồ Chí Minh',
            application.interview_details,
        )
        self.assertIn(
            'Ghi chú: Mang theo CV\nĐịa điểm: liên hệ nhân sự nếu cần đổi lịch.',
            application.interview_details,
        )
        self.assertNotIn('Địa điểm: Mang theo CV', application.interview_details)
        self.assertEqual(
            application.interview_location,
            '123 Đường Nguyễn Huệ, TP. Hồ Chí Minh',
        )
        self.assertEqual(
            application.interview_note,
            'Mang theo CV\nĐịa điểm: liên hệ nhân sự nếu cần đổi lịch.',
        )

    def test_updating_schedule_uses_the_recruiters_latest_profile_address(self):
        application = self.create_application('updated-address-candidate')
        company_profile = self.recruiter.company_profile
        company_profile.address = 'Địa chỉ mới, Đà Nẵng'
        company_profile.save(update_fields=['address'])
        interview_date = (timezone.now().date() + timedelta(days=2)).isoformat()

        response = self.update_schedule(
            application,
            interview_date=interview_date,
            interview_time='14:30',
            period='PM',
        )

        application.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertIn('Địa điểm: Địa chỉ mới, Đà Nẵng', application.interview_details)
        self.assertNotIn('Địa điểm: 123 Đường Nguyễn Huệ', application.interview_details)

    def test_past_interview_datetime_is_not_saved(self):
        application = self.create_application('past-interview-candidate', status='Pending')

        response = self.update_status(
            application,
            'Approved',
            interview_date=(timezone.now().date() - timedelta(days=1)).isoformat(),
            interview_time='09:00',
        )

        application.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(application.status, 'Pending')
        self.assertFalse(application.interview_details)

    def test_past_time_today_is_not_saved(self):
        application = self.create_application('past-time-candidate', status='Hired')
        past_time = (timezone.now() - timedelta(minutes=2)).strftime('%H:%M')

        response = self.update_schedule(
            application,
            interview_date=timezone.now().date().isoformat(),
            interview_time=past_time,
            period='',
        )

        application.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(application.interview_details)

    def test_rejection_updates_status_and_notifies_candidate(self):
        application = self.create_application('rejected-candidate', status='Pending')

        response = self.update_status(application, 'Rejected')

        application.refresh_from_db()
        notification = JobChatMessage.objects.get(receiver=application.candidate)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(application.status, 'Rejected')
        self.assertFalse(
            QualifiedCandidate.objects.filter(application=application).exists()
        )
        self.assertIn('Từ chối', notification.message)
        self.assertTrue(notification.is_application_update)

    def test_application_entering_and_leaving_qualified_status_syncs_separate_table(self):
        application = self.create_application('qualified-candidate', status='Pending')
        self.assertFalse(
            QualifiedCandidate.objects.filter(application=application).exists()
        )

        application.status = 'InterviewPassed'
        application.save()
        qualified_candidate = QualifiedCandidate.objects.get(application=application)
        self.assertEqual(qualified_candidate.status, 'Đạt phỏng vấn')

        application.status = 'Rejected'
        application.save()
        self.assertFalse(
            QualifiedCandidate.objects.filter(application=application).exists()
        )

    def test_candidate_notifications_are_shown_and_marked_read(self):
        application = self.create_application('notified-candidate', status='Pending')
        notification = JobChatMessage.objects.create(
            job=self.job,
            sender=self.recruiter,
            receiver=application.candidate,
            message="Hồ sơ ứng tuyển vừa được cập nhật trạng thái: Từ chối.",
            is_application_update=True,
        )
        request = self.request_factory.get('/candidate-applications/')
        request.user = application.candidate

        with patch('jobs.views_candidate.render', return_value=HttpResponse()) as render:
            response = candidate_applications(request)

        context = render.call_args.args[2]
        notification.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(context['notifications'], [notification])
        self.assertTrue(notification.is_read)

    def test_home_notification_badge_counts_unread_application_updates(self):
        application = self.create_application('badge-candidate', status='Pending')
        JobChatMessage.objects.create(
            job=self.job,
            sender=self.recruiter,
            receiver=application.candidate,
            message="Cập nhật trạng thái hồ sơ.",
            is_application_update=True,
        )
        request = self.request_factory.get('/')
        request.user = application.candidate

        with patch('jobs.views_home.render', return_value=HttpResponse()) as render:
            response = home_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(render.call_args.args[2]['unread_count'], 1)

    def test_dedicated_passed_list_uses_pipeline_statuses(self):
        self.create_application('passed-candidate', status='InterviewPassed')
        self.create_application('trial-candidate', status='Trial')
        self.create_application('hired-candidate', status='Hired')
        self.create_application('pending-candidate', status='Pending')
        request = self.request_factory.get('/recruiter/all-approved-candidates/')
        request.user = self.recruiter

        with patch('jobs.views_recruiter.render', return_value=HttpResponse()) as render:
            response = all_approved_candidates_view(request)

        approved_list = render.call_args.args[2]['approved_list']
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {application.status for application in approved_list},
            {'InterviewPassed', 'Trial', 'Hired'},
        )


class SePayWebhookTests(TestCase):
    def setUp(self):
        self.recruiter = User.objects.create_user(
            username='sepay-recruiter',
            email='sepay-recruiter@example.com',
            password='test-password',
            is_recruiter=True,
        )
        self.package = SubscriptionPackage.objects.create(
            name='Gói tháng',
            duration_days=30,
            post_limit=10,
            price=70000,
        )
        self.purchase = PackageTransaction.objects.create(
            recruiter=self.recruiter,
            package=self.package,
            amount=self.package.price,
        )

    def send_webhook(self, payload, secret='webhook-secret'):
        body = json.dumps(payload).encode()
        return self.client.post(
            '/webhooks/sepay/',
            data=body,
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Apikey {secret}',
        )

    def test_recruiter_creates_payment_order_before_scanning_qr(self):
        self.client.force_login(self.recruiter)

        response = self.client.post(
            '/buy-package/',
            {'action': 'create_payment', 'package_id': self.package.pk},
        )

        purchase = PackageTransaction.objects.filter(
            recruiter=self.recruiter
        ).order_by('-pk').first()
        self.assertEqual(response.status_code, 302)
        self.assertIn(f'transaction={purchase.pk}', response.url)
        self.assertTrue(purchase.payment_code.startswith('CTJ'))
        self.assertEqual(purchase.amount, self.package.price)
        self.assertEqual(purchase.status, 'pending')

    def event(self, **overrides):
        payload = {
            'id': 918273,
            'transferType': 'in',
            'accountNumber': '0368031812',
            'transferAmount': 70000,
            'content': f'Thanh toan {self.purchase.payment_code}',
            'description': 'Chuyen khoan',
        }
        payload.update(overrides)
        return payload

    @override_settings(
        SEPAY_WEBHOOK_SECRET='webhook-secret',
        SEPAY_BANK_ACCOUNT='0368031812',
    )
    def test_valid_sepay_transfer_activates_package_once(self):
        response = self.send_webhook(self.event())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'success': True})
        self.purchase.refresh_from_db()
        recruiter_account = self.recruiter.recruiter_account
        self.assertEqual(self.purchase.status, 'approved')
        self.assertEqual(self.purchase.sepay_transaction_id, '918273')
        self.assertEqual(self.purchase.sepay_received_amount, 70000)
        self.assertIsNotNone(self.purchase.verified_at)
        self.assertEqual(recruiter_account.active_package, self.package)
        self.assertEqual(recruiter_account.posts_remaining, self.package.post_limit)
        self.assertEqual(
            recruiter_account.total_posts_purchased,
            self.package.post_limit,
        )
        self.assertIsNotNone(recruiter_account.package_started_at)
        self.assertLess(
            recruiter_account.package_started_at,
            recruiter_account.package_expires_at,
        )

        self.send_webhook(self.event())
        recruiter_account.refresh_from_db()
        self.assertEqual(recruiter_account.posts_remaining, self.package.post_limit)
        self.assertEqual(
            recruiter_account.total_posts_purchased,
            self.package.post_limit,
        )

    @override_settings(
        SEPAY_WEBHOOK_SECRET='webhook-secret',
        SEPAY_BANK_ACCOUNT='0368031812',
    )
    def test_purchase_while_package_active_adds_credits_once_and_extends_expiration(self):
        self.send_webhook(self.event())
        recruiter_account = self.recruiter.recruiter_account
        first_expiration = recruiter_account.package_expires_at
        second_purchase = PackageTransaction.objects.create(
            recruiter=self.recruiter,
            package=self.package,
            amount=self.package.price,
        )
        self.package.post_limit = 12
        self.package.save(update_fields=['post_limit'])

        response = self.send_webhook(
            self.event(
                id=918274,
                content=f'Thanh toan {second_purchase.payment_code}',
            )
        )

        self.assertEqual(response.status_code, 200)
        recruiter_account.refresh_from_db()
        self.assertEqual(recruiter_account.posts_remaining, 20)
        self.assertEqual(
            recruiter_account.total_posts_purchased,
            20,
        )
        second_purchase.refresh_from_db()
        self.assertEqual(second_purchase.package_posts_count, 10)
        self.assertEqual(
            recruiter_account.package_expires_at,
            first_expiration + timedelta(days=self.package.duration_days),
        )

    def test_admin_transaction_list_shows_transaction_and_activation_times(self):
        purchase = PackageTransaction.objects.create(
            recruiter=self.recruiter,
            package=self.package,
            amount=self.package.price,
            status='approved',
        )
        purchase.verified_at = timezone.now() - timedelta(hours=1)
        purchase.save(update_fields=['verified_at'])
        PackageTransaction.objects.create(
            recruiter=self.recruiter,
            package=self.package,
            amount=self.package.price,
            status='approved',
        )
        admin = User.objects.create_user(
            username='transaction-admin',
            email='transaction-admin@example.com',
            password='test-password',
            is_staff=True,
        )
        self.client.force_login(admin)

        response = self.client.get('/custom-admin/transactions/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tạo:')
        self.assertContains(response, 'Kích hoạt:')
        self.assertContains(response, purchase.verified_at.strftime('%d/%m/%Y %H:%M'))
        self.assertNotContains(response, 'Lượt còn / thời hạn gói')
        self.assertNotContains(response, 'Trong CSDL còn:')
        self.assertNotContains(response, 'Đã mua:')

    @override_settings(SEPAY_BANK_ACCOUNT='0368031812')
    def test_recruiter_package_pages_show_total_and_monthly_spending(self):
        first_paid = PackageTransaction.objects.create(
            recruiter=self.recruiter,
            package=self.package,
            amount=70000,
            status='approved',
        )
        second_paid = PackageTransaction.objects.create(
            recruiter=self.recruiter,
            package=self.package,
            amount=30000,
            status='approved',
        )
        PackageTransaction.objects.create(
            recruiter=self.recruiter,
            package=self.package,
            amount=100000,
            status='pending',
        )
        first_paid.verified_at = timezone.now()
        first_paid.save(update_fields=['verified_at'])
        second_paid.verified_at = timezone.now()
        second_paid.save(update_fields=['verified_at'])
        request = RequestFactory().get('/recruiter/profile/')
        request.user = self.recruiter

        with patch(
            'jobs.views_recruiter.render',
            return_value=HttpResponse(),
        ) as render:
            response = recruiter_profile_view(request)

        context = render.call_args.args[2]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            context['package_spending']['total_amount'],
            100000,
        )
        self.assertEqual(
            context['package_spending']['transaction_count'],
            2,
        )
        monthly_spending = list(context['package_spending_by_month'])
        self.assertEqual(len(monthly_spending), 1)
        self.assertEqual(monthly_spending[0]['total_amount'], 100000)
        self.assertEqual(monthly_spending[0]['transaction_count'], 2)

        self.client.force_login(self.recruiter)
        response = self.client.get('/buy-package/')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Chọn tháng xem chi tiết')
        self.assertContains(response, 'Thống kê kinh phí mua gói')
        self.assertNotContains(response, 'id="monthly-spending-result"')

        selected_month = timezone.now().strftime('%Y-%m')
        response = self.client.get(
            '/buy-package/',
            {'spending_month': selected_month},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="monthly-spending-result"')
        self.assertContains(response, '100000 VNĐ')
        self.assertContains(response, '2 giao dịch đã xác nhận')

    @override_settings(
        SEPAY_WEBHOOK_SECRET='webhook-secret',
        SEPAY_BANK_ACCOUNT='0368031812',
    )
    def test_wrong_amount_does_not_activate_package(self):
        response = self.send_webhook(self.event(transferAmount=69000))

        self.assertEqual(response.status_code, 200)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.status, 'pending')
        self.assertEqual(self.purchase.sepay_received_amount, 69000)
        self.assertFalse(
            RecruiterAccount.objects.filter(user=self.recruiter).exists()
        )

    @override_settings(
        SEPAY_WEBHOOK_SECRET='webhook-secret',
        SEPAY_BANK_ACCOUNT='0368031812',
    )
    def test_wrong_payment_code_does_not_activate_package(self):
        response = self.send_webhook(self.event(content='Thanh toan khac'))

        self.assertEqual(response.status_code, 200)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.status, 'pending')

    def test_recruiter_can_upload_receipt_after_payment_is_approved(self):
        self.purchase.status = 'approved'
        self.purchase.save(update_fields=['status'])
        self.client.force_login(self.recruiter)

        response = self.client.post(
            '/buy-package/',
            {
                'action': 'upload_proof',
                'transaction_id': self.purchase.pk,
                'proof_image': SimpleUploadedFile(
                    'receipt.png',
                    b'proof image content',
                    content_type='image/png',
                ),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.purchase.refresh_from_db()
        self.assertTrue(self.purchase.proof_image.name.endswith('receipt.png'))
        self.assertEqual(self.purchase.status, 'approved')

    @override_settings(
        SEPAY_WEBHOOK_SECRET='webhook-secret',
        SEPAY_BANK_ACCOUNT='0368031812',
    )
    def test_invalid_api_key_is_rejected(self):
        response = self.send_webhook(self.event(), secret='wrong-secret')

        self.assertEqual(response.status_code, 401)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.status, 'pending')


class RecruiterAdminApprovalTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin', password='test-password', is_staff=True
        )
        self.recruiter = User.objects.create_user(
            username='pending-recruiter',
            password='test-password',
            is_recruiter=True,
            is_active=False,
            recruiter_cv='recruiter_cvs/recruiter-cv.pdf',
        )
        self.company_profile = CompanyProfile.objects.create(
            user=self.recruiter,
            company_name='Công ty tuyển dụng',
        )
        self.request_factory = RequestFactory()

    def test_admin_approval_activates_recruiter(self):
        request = self.request_factory.post('/custom-admin/user/1/approve-recruiter/')
        request.user = self.admin

        with patch('jobs.views_admin.send_mail', return_value=1) as send_mail, patch(
            'jobs.views_admin.messages.success'
        ):
            response = admin_approve_recruiter(request, self.recruiter.pk)

        self.recruiter.refresh_from_db()
        self.company_profile.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.recruiter.is_active)
        self.assertTrue(self.company_profile.is_approved)
        send_mail.assert_called_once()
        self.assertEqual(send_mail.call_args.kwargs['recipient_list'], [self.recruiter.email])

    def test_admin_approval_reports_email_failure_after_activating_recruiter(self):
        request = self.request_factory.post('/custom-admin/user/1/approve-recruiter/')
        request.user = self.admin

        with patch(
            'jobs.views_admin.send_mail',
            side_effect=OSError('SMTP unavailable'),
        ), patch('jobs.views_admin.messages.warning') as warning:
            response = admin_approve_recruiter(request, self.recruiter.pk)

        self.recruiter.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.recruiter.is_active)
        warning.assert_called_once()

    def test_admin_cannot_approve_recruiter_without_cv(self):
        self.recruiter.recruiter_cv = ''
        self.recruiter.save(update_fields=['recruiter_cv'])
        request = self.request_factory.post('/custom-admin/user/1/approve-recruiter/')
        request.user = self.admin

        with patch('jobs.views_admin.messages.error'):
            response = admin_approve_recruiter(request, self.recruiter.pk)

        self.recruiter.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.recruiter.is_active)


class RecruiterJobCreditTests(TestCase):
    def setUp(self):
        self.recruiter = User.objects.create_user(
            username='credit-recruiter',
            email='credit-recruiter@example.com',
            password='test-password',
            is_recruiter=True,
        )
        self.package = SubscriptionPackage.objects.create(
            name='Gói 2 tin',
            duration_days=30,
            post_limit=2,
            price=10000,
        )
        self.client.force_login(self.recruiter)

    def job_data(self, title):
        return {
            'title': title,
            'company_name': 'Công ty mẫu',
            'major_required': '',
            'skills_required': '',
            'max_hires': 5,
            'location': 'Hà Nội',
            'salary': '15 triệu',
            'job_type': 'Toàn thời gian',
            'description': 'Mô tả công việc',
            'requirements': 'Yêu cầu ứng viên',
            'expires_at': '',
        }

    def test_each_new_job_consumes_one_package_credit_including_final_credit(self):
        RecruiterAccount.objects.create(
            user=self.recruiter,
            active_package=self.package,
            posts_remaining=self.package.post_limit,
            total_posts_purchased=self.package.post_limit,
            free_posts_left=0,
            package_expires_at=timezone.now() + timedelta(days=30),
        )

        for title, expected_remaining in (
            ('Tin thứ nhất', 1),
            ('Tin thứ hai', 0),
        ):
            response = self.client.post(
                '/recruiter/jobs/create/',
                self.job_data(title),
            )
            account = self.recruiter.recruiter_account
            account.refresh_from_db()

            self.assertEqual(response.status_code, 302)
            self.assertEqual(account.posts_remaining, expected_remaining)
            self.assertEqual(
                account.total_posts_purchased,
                self.package.post_limit,
            )

        response = self.client.get('/recruiter/jobs/create/')
        self.assertRedirects(response, '/buy-package/')
        self.assertEqual(Job.objects.filter(recruiter=self.recruiter).count(), 2)

    def test_initial_free_post_is_consumed_before_recruiter_needs_a_package(self):
        account = RecruiterAccount.objects.create(user=self.recruiter)

        response = self.client.post(
            '/recruiter/jobs/create/',
            self.job_data('Tin miễn phí đầu tiên'),
        )

        account.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(account.free_posts_left, 0)
        self.assertEqual(account.posts_remaining, 0)
        self.assertEqual(account.total_posts_purchased, 0)
        self.assertEqual(Job.objects.filter(recruiter=self.recruiter).count(), 1)
        self.assertRedirects(
            self.client.get('/recruiter/jobs/create/'),
            '/buy-package/',
        )

    def test_cloning_a_job_consumes_one_package_credit(self):
        account = RecruiterAccount.objects.create(
            user=self.recruiter,
            active_package=self.package,
            posts_remaining=1,
            total_posts_purchased=self.package.post_limit,
            package_expires_at=timezone.now() + timedelta(days=30),
        )
        source_job = Job.objects.create(
            title='Tin gốc',
            company_name='Công ty mẫu',
            location='Hà Nội',
            salary='15 triệu',
            job_type='Toàn thời gian',
            description='Mô tả công việc',
            requirements='Yêu cầu ứng viên',
            recruiter=self.recruiter,
        )

        response = self.client.post(
            f'/recruiter/job/clone/{source_job.pk}/',
            self.job_data('Tin được nhân bản'),
        )

        account.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(account.posts_remaining, 0)
        self.assertEqual(
            account.total_posts_purchased,
            self.package.post_limit,
        )
        self.assertEqual(Job.objects.filter(recruiter=self.recruiter).count(), 2)

    def test_expired_package_does_not_consume_package_credit_instead_uses_free_credit(self):
        account = RecruiterAccount.objects.create(
            user=self.recruiter,
            active_package=self.package,
            posts_remaining=2,
            total_posts_purchased=10,
            free_posts_left=1,
            package_expires_at=timezone.now() - timedelta(seconds=1),
        )

        response = self.client.post(
            '/recruiter/jobs/create/',
            self.job_data('Tin dùng lượt miễn phí'),
        )

        account.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(account.posts_remaining, 2)
        self.assertEqual(account.total_posts_purchased, 10)
        self.assertEqual(account.free_posts_left, 0)
        self.assertEqual(Job.objects.filter(recruiter=self.recruiter).count(), 1)


class AdminManageJobsByRecruiterTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='jobs-admin',
            email='jobs-admin@example.com',
            password='test-password',
            is_staff=True,
        )
        self.recruiter = User.objects.create_user(
            username='jobs-recruiter',
            email='jobs-recruiter@example.com',
            password='test-password',
            is_recruiter=True,
        )
        self.request_factory = RequestFactory()

    def create_job(self, title, expires_at=None):
        return Job.objects.create(
            title=title,
            company_name='Công ty mẫu',
            location='Hà Nội',
            salary='15 triệu',
            job_type='Toàn thời gian',
            description='Mô tả công việc',
            requirements='Yêu cầu ứng viên',
            recruiter=self.recruiter,
            expires_at=expires_at,
        )

    def test_admin_can_view_recruiters_and_job_counts(self):
        self.create_job('Backend developer')
        request = self.request_factory.get('/custom-admin/jobs/')
        request.user = self.admin

        with patch('jobs.views_admin.render', return_value=HttpResponse()) as render:
            response = admin_manage_jobs(request)

        recruiters = render.call_args.args[2]['recruiters']
        listed_recruiter = next(
            recruiter
            for recruiter in recruiters
            if recruiter.pk == self.recruiter.pk
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(listed_recruiter.job_count, 1)

    def test_admin_recruiter_expander_shows_package_purchases_and_jobs(self):
        package = SubscriptionPackage.objects.create(
            name='Gói 30 tin',
            duration_days=30,
            post_limit=30,
            price=70000,
        )
        RecruiterAccount.objects.create(
            user=self.recruiter,
            active_package=package,
            posts_remaining=8,
            total_posts_purchased=30,
            free_posts_left=2,
            package_started_at=timezone.now() - timedelta(days=2),
            package_expires_at=timezone.now() + timedelta(days=28),
        )
        PackageTransaction.objects.create(
            recruiter=self.recruiter,
            package=package,
            amount=70000,
            status='approved',
        )
        self.create_job('Tin tuyển dụng cần theo dõi')
        self.client.force_login(self.admin)

        response = self.client.get('/custom-admin/jobs/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Lượt miễn phí còn')
        self.assertContains(response, 'Lượt gói còn sử dụng')
        self.assertContains(response, 'Gói 30 tin')
        self.assertContains(response, 'Tin tuyển dụng cần theo dõi')
        self.assertContains(response, '1 lần đã kích hoạt')
        self.assertContains(response, '10 lượt đăng còn dùng')

    def test_selected_recruiter_package_section_shows_only_package_details(self):
        package = SubscriptionPackage.objects.create(
            name='Gói 30 tin',
            duration_days=30,
            post_limit=30,
            price=70000,
        )
        RecruiterAccount.objects.create(
            user=self.recruiter,
            active_package=package,
            posts_remaining=8,
            total_posts_purchased=30,
            free_posts_left=2,
            package_started_at=timezone.now() - timedelta(days=2),
            package_expires_at=timezone.now() + timedelta(days=28),
        )
        PackageTransaction.objects.create(
            recruiter=self.recruiter,
            package=package,
            amount=70000,
            status='approved',
        )
        self.create_job('Tin tuyển dụng cần theo dõi')
        self.client.force_login(self.admin)

        response = self.client.get(
            f'/custom-admin/jobs/?recruiter={self.recruiter.pk}&all=1&section=packages'
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tổng lượt đã mua')
        self.assertContains(response, '<div class="fs-4 fw-bold">30</div>', html=True)
        self.assertNotContains(response, 'Số lượt còn lại trong CSDL')
        self.assertContains(response, 'Tổng lượt đăng dùng được hiện tại: 10')
        self.assertContains(response, 'Gói 30 tin')
        self.assertContains(response, 'Lịch sử mua gói')
        self.assertNotContains(response, 'Tin tuyển dụng cần theo dõi')

    def test_selected_recruiter_active_and_expired_sections_show_only_matching_jobs(self):
        self.create_job('Tin còn hạn mẫu')
        self.create_job('Tin hết hạn mẫu', timezone.now() - timedelta(days=1))
        self.client.force_login(self.admin)

        for section, shown_title, hidden_title in (
            ('active', 'Tin còn hạn mẫu', 'Tin hết hạn mẫu'),
            ('expired', 'Tin hết hạn mẫu', 'Tin còn hạn mẫu'),
        ):
            response = self.client.get(
                f'/custom-admin/jobs/?recruiter={self.recruiter.pk}&all=1&section={section}'
            )

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, shown_title)
            self.assertNotContains(response, hidden_title)
            self.assertNotContains(response, 'Lịch sử mua gói')

    def test_admin_jobs_are_grouped_by_expiration_for_selected_recruiter(self):
        self.create_job('Active job')
        self.create_job('Expired job', timezone.now() - timedelta(days=1))
        for status_filter, expected_title in (
            ('active', 'Active job'),
            ('expired', 'Expired job'),
        ):
            request = self.request_factory.get(
                f'/custom-admin/jobs/?recruiter={self.recruiter.pk}&status={status_filter}'
            )
            request.user = self.admin

            with patch('jobs.views_admin.render', return_value=HttpResponse()) as render:
                response = admin_manage_jobs(request)

            context = render.call_args.args[2]
            self.assertEqual(response.status_code, 200)
            self.assertEqual(context['selected_recruiter'], self.recruiter)
            self.assertEqual(context['status_filter'], status_filter)
            self.assertEqual([job.title for job in context['jobs']], [expected_title])