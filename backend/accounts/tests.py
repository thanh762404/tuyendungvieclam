import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.messages.storage.fallback import FallbackStorage
from django.db import IntegrityError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from docx import Document

from accounts.forms import ProfileUpdateForm, SignUpForm
from accounts.models import Profile, User
from accounts.views import profile_edit_view, signup_view


class CandidateProfileCvSkillSyncTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(
			username='candidate',
			email='candidate@example.com',
			password='test-password',
			is_candidate=True,
		)
		self.profile = Profile.objects.create(
			user=self.user,
			major='Công nghệ thông tin',
			skills='HTML/CSS',
			cv_skills='Tester, NodeJS',
			cv_file='cvs/old-cv.pdf',
		)
		self.request_factory = RequestFactory()

	def submit_profile_update(self, data):
		request = self.request_factory.post('/accounts/profile/edit/', data=data)
		request.user = self.user
		request.session = {}
		request._messages = FallbackStorage(request)
		with patch('accounts.views.redirect', return_value=HttpResponse()):
			return profile_edit_view(request)

	def profile_form_data(self):
		return {
			'username': self.user.username,
			'email': self.user.email,
			'first_name': self.user.first_name,
			'last_name': self.user.last_name,
			'phone': '',
			'bio': '',
			'major': 'Công nghệ thông tin',
			'skills': 'HTML/CSS',
		}

	def test_replacing_cv_refreshes_extracted_skills(self):
		data = self.profile_form_data()
		document = Document()
		document.add_paragraph('Experience with Python, Django, and HTML/CSS.')
		cv_content = BytesIO()
		document.save(cv_content)
		data['cv_file'] = SimpleUploadedFile(
			'new-cv.docx',
			cv_content.getvalue(),
			content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
		)

		with tempfile.TemporaryDirectory() as media_root:
			with override_settings(MEDIA_ROOT=media_root):
				self.profile.cv_file.save('old-cv.pdf', ContentFile(b'%PDF old'), save=True)
				old_cv_path = Path(self.profile.cv_file.path)
				response = self.submit_profile_update(data)
				self.profile.refresh_from_db()
				self.assertFalse(old_cv_path.exists())
				self.assertTrue(Path(self.profile.cv_file.path).exists())

		self.assertEqual(response.status_code, 200)
		self.assertEqual(self.profile.cv_skills, 'python, django, html/css')
		self.assertTrue(self.profile.cv_file.name.endswith('new-cv.docx'))

	def test_removing_cv_clears_saved_extracted_skills(self):
		data = self.profile_form_data()
		data['cv_file-clear'] = 'on'

		with tempfile.TemporaryDirectory() as media_root:
			with override_settings(MEDIA_ROOT=media_root):
				self.profile.cv_file.save('old-cv.pdf', ContentFile(b'%PDF old'), save=True)
				old_cv_path = Path(self.profile.cv_file.path)
				response = self.submit_profile_update(data)

		self.profile.refresh_from_db()
		self.assertEqual(response.status_code, 200)
		self.assertFalse(self.profile.cv_file)
		self.assertEqual(self.profile.cv_skills, '')
		self.assertFalse(old_cv_path.exists())


class CandidateMajorSkillValidationTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(
			username='candidate', email='candidate@example.com', password='test-password'
		)
		self.profile = Profile.objects.create(user=self.user)

	def test_profile_accepts_multiple_skills_from_selected_major(self):
		form = ProfileUpdateForm(
			data={
				'phone': '',
				'bio': '',
				'major': 'Công nghệ thông tin',
				'skills': 'Python, MySQL',
			},
			instance=self.profile,
		)

		self.assertTrue(form.is_valid(), form.errors)

	def test_profile_rejects_skills_from_another_major(self):
		form = ProfileUpdateForm(
			data={
				'phone': '',
				'bio': '',
				'major': 'Logistics',
				'skills': 'Python',
			},
			instance=self.profile,
		)

		self.assertFalse(form.is_valid())
		self.assertIn('skills', form.errors)


class SignupDuplicateUsernameTests(TestCase):
	def setUp(self):
		self.request_factory = RequestFactory()

	def signup_data(self, username):
		return {
			'username': username,
			'email': f'{username}@example.com',
			'password1': 'StrongPassword!9284',
			'password2': 'StrongPassword!9284',
			'role': 'candidate',
			'phone': '0123456789',
			'major': 'Công nghệ thông tin',
			'skills': 'Python',
		}

	def post_signup(self, data):
		request = self.request_factory.post('/accounts/signup/', data=data)
		with patch('accounts.views.render', return_value=HttpResponse()) as render:
			response = signup_view(request)
		return response, render.call_args.args[2]['form']

	def test_existing_username_returns_form_error(self):
		User.objects.create_user(username='test110', password='test-password')

		response, form = self.post_signup(self.signup_data('test110'))

		self.assertEqual(response.status_code, 200)
		self.assertIn('username', form.errors)

	def test_concurrent_duplicate_username_returns_form_error_not_integrity_error(self):
		duplicate_error = IntegrityError(
			"(1062, \"Duplicate entry 'race-candidate' for key 'username'\")"
		)

		with patch('accounts.models.User.save', side_effect=duplicate_error):
			response, form = self.post_signup(self.signup_data('race-candidate'))

		self.assertEqual(response.status_code, 200)
		self.assertIn('username', form.errors)
		self.assertEqual(form.errors['username'][0], 'Tên đăng nhập này đã được sử dụng. Vui lòng chọn tên khác.')

	def test_signup_rejects_skills_from_another_major(self):
		form = SignUpForm(
			data={
				'username': 'new-candidate',
				'email': 'new@example.com',
				'password1': 'StrongPassword!928',
				'password2': 'StrongPassword!928',
				'role': 'candidate',
				'phone': '0123456789',
				'major': 'Logistics',
				'skills': 'Python',
			}
		)

		self.assertFalse(form.is_valid())
		self.assertIn('skills', form.errors)


class RecruiterSignupApprovalTests(TestCase):
	def test_recruiter_signup_requires_cv(self):
		form = SignUpForm(
			data={
				'username': 'new-recruiter',
				'email': 'recruiter@example.com',
				'password1': 'StrongPassword!9284',
				'password2': 'StrongPassword!9284',
				'role': 'recruiter',
				'phone': '0123456789',
			},
		)

		self.assertFalse(form.is_valid())
		self.assertIn('recruiter_cv', form.errors)

	def test_recruiter_signup_stays_inactive_until_admin_approval(self):
		form = SignUpForm(
			data={
				'username': 'new-recruiter',
				'email': 'recruiter@example.com',
				'password1': 'StrongPassword!9284',
				'password2': 'StrongPassword!9284',
				'role': 'recruiter',
				'phone': '0123456789',
			},
			files={
				'recruiter_cv': SimpleUploadedFile(
					'recruiter-cv.pdf', b'%PDF-1.4 test', content_type='application/pdf'
				)
			},
		)

		self.assertTrue(form.is_valid(), form.errors)
		user = form.save(commit=False)
		self.assertTrue(user.is_recruiter)
		self.assertFalse(user.is_active)
		self.assertEqual(user.recruiter_cv.name, 'recruiter-cv.pdf')
