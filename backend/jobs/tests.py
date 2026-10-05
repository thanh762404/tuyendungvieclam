import json
import os
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404, HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from accounts.models import Profile, User
from jobs.forms import JobForm
from jobs.models import Application, Job, JobChatMessage
from jobs.services import send_interview_reminder_email
from jobs.views_candidate import (
    apply_job,
    candidate_applications,
    update_application_status,
)
from jobs.views_chat import get_job_chat_unread_count, send_job_chat_message
from jobs.views_home import home_view
from jobs.views_admin import admin_approve_recruiter, admin_manage_jobs
from jobs.views_recruiter import (
    all_approved_candidates_view,
    job_achieved_candidates_view,
    mark_job_chat_read,
    recruiter_job_list,
)


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
            username='recruiter', password='test-password', is_recruiter=True
        )
        self.candidate = User.objects.create_user(
            username='candidate', password='test-password', is_candidate=True
        )
        self.profile = Profile.objects.create(
            user=self.candidate,
            major='Công nghệ thông tin',
            skills='Python',
            cv_skills='Django',
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
        self.stale_cv_skill_job = self.create_job(
            recruiter, 'Django Developer', 'Công nghệ thông tin', 'Django'
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
        self.assertNotIn(self.stale_cv_skill_job, context['suggested_jobs'])

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

    def test_uploaded_cv_skills_can_recommend_jobs_outside_profile_major(self):
        self.profile.major = 'Tài chính – Ngân hàng'
        self.profile.skills = 'Tín dụng ngân hàng'
        self.profile.cv_skills = 'Tester, Node.js, ReactJS'
        self.profile.cv_file = 'cvs/candidate.pdf'
        self.profile.save()
        finance_job = self.create_job(
            self.matching_job.recruiter,
            'Chuyên viên Tín dụng ngân hàng',
            'Tài chính – Ngân hàng',
            'Tín dụng ngân hàng, Chăm sóc khách hàng',
        )
        cv_job = self.create_job(
            self.matching_job.recruiter,
            'Kỹ sư Kiểm thử Phần mềm Tester',
            'Công nghệ thông tin',
            'MySQL, Tester',
        )
        unrelated_job = self.create_job(
            self.matching_job.recruiter,
            'Nhân viên Quản lý kho',
            'Logistics',
            'Quản lý kho, Xuất nhập khẩu',
        )

        with patch('jobs.views_home.extract_skills_from_file', return_value=[]):
            _, context = self.get_home_context()

        self.assertEqual(
            list(context['suggested_jobs']),
            [finance_job, cv_job],
        )
        self.assertNotIn(unrelated_job, context['suggested_jobs'])

    def test_cv_skills_are_combined_with_registered_skills(self):
        self.profile.cv_file = 'cvs/candidate.pdf'
        self.profile.save()
        cv_skill_job = self.create_job(
            self.matching_job.recruiter, 'Django Developer', 'Công nghệ thông tin', 'Django'
        )

        with patch('jobs.views_home.extract_skills_from_file', return_value=['Django']):
            response, context = self.get_home_context()

        self.assertEqual(
            set(context['suggested_jobs']),
            {self.matching_job, self.stale_cv_skill_job, cv_skill_job},
        )

    def test_recommendations_rank_by_skill_coverage_and_ignore_description_mentions(self):
        self.profile.skills = 'HTML/CSS, MySQL'
        self.profile.cv_skills = 'Tester, Node.js, ReactJS, React'
        self.profile.cv_file = 'cvs/candidate.pdf'
        self.profile.save()

        profile_skill_job = self.create_job(
            self.matching_job.recruiter,
            'HTML/CSS Developer',
            'Công nghệ thông tin',
            'HTML/CSS, Python, Django',
        )
        weak_profile_match_job = self.create_job(
            self.matching_job.recruiter,
            'Python Django Backend',
            'Công nghệ thông tin',
            'Python, MySQL, Django, HTML/CSS',
        )
        tester_job = self.create_job(
            self.matching_job.recruiter,
            'Kỹ sư kiểm thử (QC/Tester)',
            'Công nghệ thông tin',
            'MySQL, Tester',
        )
        frontend_job = self.create_job(
            self.matching_job.recruiter,
            'Lập trình viên Fullstack Node.js ReactJS',
            'Công nghệ thông tin',
            'ReactJS, MySQL, HTML/CSS, Node.js',
        )
        data_job = self.create_job(
            self.matching_job.recruiter,
            'Kỹ sư Machine Learning',
            'Công nghệ thông tin',
            'Python, MySQL',
        )
        automation_job = self.create_job(
            self.matching_job.recruiter,
            'Automation Tester Python',
            'Công nghệ thông tin',
            'Python, MySQL, Tester',
        )
        web_job = self.create_job(
            self.matching_job.recruiter,
            'Fullstack Python ReactJS',
            'Công nghệ thông tin',
            'Python, ReactJS, MySQL, Django',
        )
        weak_match_job = self.create_job(
            self.matching_job.recruiter,
            'Lập trình viên Backend',
            'Công nghệ thông tin',
            'Python, MySQL, Django',
        )
        no_match_job = self.create_job(
            self.matching_job.recruiter,
            'Java Developer',
            'Công nghệ thông tin',
            'Java, Python, Django',
        )
        description_only_job = self.create_job(
            self.matching_job.recruiter,
            'Kỹ sư Java',
            'Công nghệ thông tin',
            '',
            description='Có nhắc đến MySQL nhưng không khai báo là kỹ năng yêu cầu.',
        )

        with patch('jobs.views_home.extract_skills_from_file', return_value=[]):
            _, context = self.get_home_context()

        self.assertEqual(
            list(context['suggested_jobs']),
                [
                    frontend_job,
                    weak_profile_match_job,
                    tester_job,
                    automation_job,
                    web_job,
                    data_job,
                    profile_skill_job,
                    weak_match_job,
                ],
        )
        self.assertNotIn(no_match_job, context['suggested_jobs'])
        self.assertNotIn(description_only_job, context['suggested_jobs'])
        suggested_by_id = {job.pk: job for job in context['suggested_jobs']}
        self.assertEqual(
            suggested_by_id[profile_skill_job.pk].recommendation_profile_skills,
            ['HTML/CSS'],
        )
        self.assertEqual(
            suggested_by_id[frontend_job.pk].recommendation_cv_skills,
            ['Node.js', 'ReactJS'],
        )


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
            username=username, password='test-password', is_candidate=True
        )
        return Application.objects.create(
            job=self.job,
            candidate=candidate,
            cv_file=f'applications_cvs/{username}.pdf',
            status=status,
        )

    def update_status(self, application, status, interview_date='', interview_time=''):
        request = self.request_factory.post(
            f'/application/{application.pk}/update/',
            {
                'status': status,
                'interview_date': interview_date,
                'interview_time': interview_time,
                'interview_note': '',
            },
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
        self.assertIn('trong vòng 24 giờ', send_mail.call_args.args[1])

    def test_trial_status_emails_work_schedule_and_notifies_candidate(self):
        application = self.create_application('trial-notice-candidate', status='Approved')
        application.candidate.email = 'candidate@example.com'
        application.candidate.save(update_fields=['email'])

        with patch('jobs.services.send_mail', return_value=1) as send_mail:
            response = self.update_status(
                application,
                'Trial',
                interview_date='2026-10-05',
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
        self.assertIn('2026-10-05', notification.message)
        self.assertEqual(send_mail.call_args.args[3], ['candidate@example.com'])
        self.assertIn('Đang thử việc', send_mail.call_args.args[1])
        self.assertIn('Lịch bắt đầu thử việc/đi làm', send_mail.call_args.args[1])
        self.assertIn('2026-10-05', send_mail.call_args.args[1])

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

    def test_job_achieved_candidates_shows_only_that_jobs_pipeline(self):
        self.create_application('passed-candidate', status='InterviewPassed')
        self.create_application('trial-candidate', status='Trial')
        self.create_application('pending-candidate', status='Pending')
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
            username='recruiter', password='test-password', is_recruiter=True
        )
        self.candidate = User.objects.create_user(
            username='candidate', password='test-password', is_candidate=True
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

    def create_application(self, username, status='Approved'):
        candidate = User.objects.create_user(
            username=username, password='test-password', is_candidate=True
        )
        return Application.objects.create(
            job=self.job,
            candidate=candidate,
            cv_file=f'applications_cvs/{username}.pdf',
            status=status,
        )

    def update_status(self, application, status, interview_date='', interview_time=''):
        request = self.request_factory.post(
            f'/application/{application.pk}/update/',
            {
                'status': status,
                'interview_date': interview_date,
                'interview_time': interview_time,
                'interview_note': '',
            },
        )
        request.user = self.recruiter
        request.session = {}
        request._messages = FallbackStorage(request)
        with patch('jobs.views_candidate.redirect', return_value=HttpResponse()), patch(
            'jobs.views_candidate.render', return_value=HttpResponse()
        ):
            return update_application_status(request, application.pk)

    def test_candidate_gets_immediate_ai_reply_with_current_and_other_jobs_context(self):
        other_job = Job.objects.create(
            title='Frontend React Developer',
            location='Đà Nẵng',
            salary='18 triệu',
            job_type='Full-time',
            description='Phát triển giao diện React.',
            requirements='Biết ReactJS.',
            major_required='Công nghệ thông tin',
            skills_required='ReactJS, HTML/CSS',
            recruiter=self.recruiter,
            status='Approved',
        )
        Job.objects.create(
            title='Tin chưa duyệt',
            location='Hà Nội',
            salary='Thoả thuận',
            job_type='Full-time',
            description='Không đưa vào gợi ý.',
            requirements='',
            recruiter=self.recruiter,
            status='Pending',
        )
        request = RequestFactory().post(
            f'/jobs/{self.job.pk}/chat/send/',
            {'message': 'Công việc này yêu cầu kỹ năng gì?'},
        )
        request.user = self.candidate
        generated_response = type('GeneratedResponse', (), {'text': 'Cần Python và Django.'})()

        with patch.dict(os.environ, {'GOOGLE_API_KEY': 'test-key'}):
            with patch('jobs.views_chat.genai', create=True) as genai_module:
                client_class = genai_module.Client
                client_class.return_value.models.generate_content.return_value = generated_response
                response = send_job_chat_message(request, self.job.pk)

        response_data = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response_data['status'], 'success')
        self.assertEqual(JobChatMessage.objects.count(), 2)
        ai_message = JobChatMessage.objects.get(sender=self.recruiter, receiver=self.candidate)
        self.assertEqual(ai_message.message, 'Cần Python và Django.')
        prompt = client_class.return_value.models.generate_content.call_args.kwargs['contents']
        self.assertIn(self.job.title, prompt)
        self.assertIn(other_job.title, prompt)
        self.assertNotIn('Tin chưa duyệt', prompt)

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

        response = self.update_status(
            application,
            'Approved',
            interview_date='2026-10-05',
            interview_time='14:30',
        )

        self.assertEqual(response.status_code, 200)
        application.refresh_from_db()
        notification = JobChatMessage.objects.get(receiver=application.candidate)
        self.assertEqual(application.status, 'Approved')
        self.assertIn('Ngày: 2026-10-05', application.interview_details)
        self.assertIn('Giờ: 14:30', application.interview_details)
        self.assertIn('Đã duyệt / Phỏng vấn', notification.message)
        self.assertIn('2026-10-05', notification.message)

    def test_rejection_updates_status_and_notifies_candidate(self):
        application = self.create_application('rejected-candidate', status='Pending')

        response = self.update_status(application, 'Rejected')

        application.refresh_from_db()
        notification = JobChatMessage.objects.get(receiver=application.candidate)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(application.status, 'Rejected')
        self.assertIn('Từ chối', notification.message)
        self.assertTrue(notification.is_application_update)

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
        self.request_factory = RequestFactory()

    def test_admin_approval_activates_recruiter(self):
        request = self.request_factory.post('/custom-admin/user/1/approve-recruiter/')
        request.user = self.admin

        with patch('jobs.views_admin.messages.success'):
            response = admin_approve_recruiter(request, self.recruiter.pk)

        self.recruiter.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.recruiter.is_active)

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


class AdminManageJobsByRecruiterTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='jobs-admin', password='test-password', is_staff=True
        )
        self.recruiter = User.objects.create_user(
            username='jobs-recruiter', password='test-password', is_recruiter=True
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
