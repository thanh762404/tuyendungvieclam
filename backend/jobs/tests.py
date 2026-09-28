from django.test import TestCase

from accounts.models import User
from jobs.models import Job, JobChatMessage


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
