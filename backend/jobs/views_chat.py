import os
from dotenv import load_dotenv

from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

try:
    from google import genai
except ImportError:
    genai = None

from .models import Job, JobChatMessage

# Tải các biến từ file .env ngay khi file này chạy
load_dotenv()
@login_required
def send_job_chat_message(request, pk):
    if request.method == "POST":
        try:
            job = get_object_or_404(Job, pk=pk)
            message_text = request.POST.get("message", "").strip()

            if not message_text:
                return JsonResponse(
                    {"status": "error", "error": "Tin nhắn trống"}, status=400
                )

            if request.user == job.recruiter:
                candidate_id = request.POST.get("candidate_id")
                if not candidate_id:
                    latest_msg = (
                        JobChatMessage.objects.filter(job=job)
                        .exclude(sender=request.user)
                        .order_by("-created_at")
                        .first()
                    )
                    if latest_msg:
                        receiver = latest_msg.sender
                    else:
                        return JsonResponse(
                            {
                                "status": "error",
                                "error": "Thiếu ID ứng viên hoặc chưa có cuộc hội thoại nào",
                            },
                            status=400,
                        )
                else:
                    User = get_user_model()
                    receiver = get_object_or_404(User, pk=candidate_id)
            else:
                receiver = job.recruiter

            if receiver == request.user:
                return JsonResponse(
                    {"status": "error", "error": "Không thể gửi tin nhắn cho chính mình"}, status=400
                )

            # 1. Lưu tin nhắn của ứng viên
            chat = JobChatMessage(
                job=job,
                sender=request.user,
                receiver=receiver,
                sender_name=request.user.username,
                receiver_name=receiver.username,
                message=message_text,
                is_read=False,
            )
            chat.save()

            # 2. Nếu người gửi là ứng viên, kích hoạt AI trả lời tự động thông minh
            if request.user != job.recruiter:
                company_name = job.get_company_name or "Công ty"
                
                # Lấy danh sách các công việc khác do nhà tuyển dụng này đăng (tối đa 5 việc)
                other_jobs = Job.objects.filter(
                    recruiter=job.recruiter,
                    status="Approved",
                ).filter(
                    Q(expires_at__isnull=True) | Q(expires_at__gte=timezone.now())
                ).exclude(pk=job.pk).order_by("-created_at")[:5]
                if other_jobs.exists():
                    other_jobs_text = "\n".join([
                        f"- Vị trí: {j.title} | Ngành: {j.major_required or 'Không nêu'} "
                        f"| Kỹ năng: {j.skills_required or 'Không nêu'} | Mức lương: {j.salary} "
                        f"| Địa điểm: {j.location} | Mô tả: {j.description[:200]}..."
                        for j in other_jobs
                    ])
                else:
                    other_jobs_text = "Hiện nhà tuyển dụng không có vị trí nào khác."

                prompt = f"""
                Bạn là trợ lý AI tuyển dụng tự động của công ty/nhà tuyển dụng '{company_name}'. 
                Ứng viên đang nhắn tin từ tin tuyển dụng vị trí: "{job.title}".
                
                Thông tin chi tiết công việc hiện tại này:
                - Mức lương: {job.salary}
                - Địa điểm: {job.location}
                - Ngành yêu cầu: {job.major_required or 'Không nêu'}
                - Kỹ năng yêu cầu: {job.skills_required or 'Không nêu'}
                - Mô tả: {job.description}
                - Yêu cầu: {job.requirements}

                Danh sách các vị trí công việc KHÁC cũng do nhà tuyển dụng này đăng tuyển:
                {other_jobs_text}

                Quy tắc phản hồi cho AI:
                1. Trả lời bằng tiếng Việt, ngắn gọn, lịch sự và chỉ dựa trên dữ liệu được cung cấp.
                2. Nếu ứng viên hỏi về công việc hiện tại (lương, địa điểm, ngành, kỹ năng, yêu cầu...): Hãy trả lời theo thông tin công việc hiện tại; không tự bịa quyền lợi hoặc điều kiện.
                3. Nếu ứng viên hỏi vị trí khác: Chỉ giới thiệu tin trong "Danh sách các vị trí công việc KHÁC" ở trên, nêu rõ vị trí, kỹ năng phù hợp, lương và địa điểm.
                4. Nếu không có tin phù hợp hoặc câu hỏi ngoài tuyển dụng, hãy nói rõ chưa có thông tin và đề nghị nhà tuyển dụng phản hồi; không bịa câu trả lời.

                Tin nhắn của ứng viên: "{message_text}"
                """

                try:
                    if genai is None:
                        raise RuntimeError("Google GenAI SDK is not installed")

                    # Lấy API key từ biến môi trường thay vì viết cứng
                    api_key = os.getenv("GOOGLE_API_KEY")
    
                    # Khởi tạo client với api_key vừa lấy
                    client = genai.Client(api_key=api_key)
                    response = client.models.generate_content(
                        model='gemini-3.6-flash',
                        contents=prompt,
                    )
                    auto_reply = response.text.strip()
                except Exception as e:
                    print("--- LỖI GỌI GEMINI AI ---:", str(e))
                    auto_reply = "Cảm ơn bạn! Nhà tuyển dụng đã nhận được tin nhắn và sẽ phản hồi trong thời gian sớm nhất."

                # Lưu câu trả lời tự động của AI dưới danh nghĩa Nhà tuyển dụng gửi cho ứng viên
                JobChatMessage.objects.create(
                    job=job,
                    sender=job.recruiter,
                    receiver=request.user,
                    sender_name=job.recruiter.username,
                    receiver_name=request.user.username,
                    message=auto_reply,
                    is_read=False,
                )

            return JsonResponse(
                {
                    "status": "success",
                    "message": chat.message,
                    "created_at": chat.created_at.strftime("%H:%M"),
                    "saved_id": chat.pk,
                }
            )
        except Exception as e:
            return JsonResponse({"status": "error", "error": str(e)}, status=500)

    return JsonResponse({"status": "error", "error": "Invalid request method"}, status=400)


@login_required
def get_job_chat_history(request, pk):
    try:
        job = get_object_or_404(Job, pk=pk)

        if request.user == job.recruiter:
            candidate_id = request.GET.get("candidate_id")
            if not candidate_id:
                latest_msg = (
                    JobChatMessage.objects.filter(job=job)
                    .exclude(sender=request.user)
                    .order_by("-created_at")
                    .first()
                )
                if latest_msg:
                    other_user = latest_msg.sender
                else:
                    return JsonResponse({"messages": []})
            else:
                User = get_user_model()
                other_user = get_object_or_404(User, pk=candidate_id)
        else:
            other_user = job.recruiter

        chat_messages = (
            JobChatMessage.objects.filter(job=job)
            .filter(
                Q(sender=request.user, receiver=other_user)
                | Q(sender=other_user, receiver=request.user)
            )
            .order_by("created_at")
        )

        data = []
        for m in chat_messages:
            data.append(
                {
                    "sender_id": m.sender.id,
                    "sender_name": m.sender.username,
                    "is_me": m.sender.id == request.user.id,
                    "message": m.message,
                    "created_at": m.created_at.strftime("%H:%M"),
                }
            )

        return JsonResponse({"messages": data})
    except Exception as e:
        return JsonResponse({"status": "error", "error": str(e)}, status=500)


@login_required
def get_job_chat_unread_count(request, pk):
    job = get_object_or_404(Job, pk=pk)
    if request.user == job.recruiter:
        unread_count = JobChatMessage.objects.filter(
            job=job,
            receiver=request.user,
            is_read=False,
        ).count()
    else:
        unread_count = JobChatMessage.objects.filter(
            job=job,
            sender=job.recruiter,
            receiver=request.user,
            is_read=False,
        ).count()
    return JsonResponse({"unread_count": unread_count})