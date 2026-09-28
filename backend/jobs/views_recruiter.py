from datetime import datetime, timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import CompanyProfileForm, JobForm
from .models import (
    Application,
    CompanyProfile,
    Job,
    JobChatMessage,
    PackageTransaction,
    RecruiterAccount,
    SubscriptionPackage,
)


@login_required
def recruiter_profile_view(request):
    """View cho phép nhà tuyển dụng cập nhật thông tin công ty và logo riêng"""
    if not getattr(request.user, "is_recruiter", False):
        return redirect("home")

    profile, created = CompanyProfile.objects.get_or_create(
        user=request.user,
        defaults={"company_name": request.user.username},
    )

    if request.method == "POST":
        form = CompanyProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Cập nhật thông tin công ty thành công!")
            return redirect("recruiter_profile")
    else:
        form = CompanyProfileForm(instance=profile)

    return render(
        request, "jobs/recruiter_profile.html", {"form": form, "profile": profile}
    )


@login_required
def recruiter_job_list(request):
    jobs = Job.objects.filter(recruiter=request.user).order_by("-created_at")
    employer_jobs = Job.objects.filter(recruiter=request.user)
    chat_messages = JobChatMessage.objects.filter(job__in=employer_jobs)

    total_unread = chat_messages.filter(
        receiver=request.user, is_read=False
    ).count()

    conversations_dict = {}
    for msg in chat_messages.order_by("created_at"):
        candidate = msg.sender if msg.sender != request.user else msg.receiver
        if candidate == request.user:
            continue

        key = (msg.job_id, candidate.id)
        unread_for_this_candidate = chat_messages.filter(
            job_id=msg.job_id,
            sender=candidate,
            receiver=request.user,
            is_read=False,
        ).count()

        conversations_dict[key] = {
            "job_id": msg.job_id,
            "candidate": candidate,
            "last_message": msg.message,
            "last_time": msg.created_at,
            "unread_count": unread_for_this_candidate,
        }

    chat_conversations = list(conversations_dict.values())

    return render(
        request,
        "jobs/recruiter_job_list.html",
        {
            "jobs": jobs,
            "chat_conversations": chat_conversations,
            "total_unread": total_unread,
        },
    )


@login_required
def mark_job_chat_read(request, pk):
    if request.method == "POST":
        candidate_id = request.POST.get("candidate_id")
        if candidate_id:
            JobChatMessage.objects.filter(
                job_id=pk,
                sender_id=candidate_id,
                receiver=request.user,
                is_read=False,
            ).update(is_read=True)
            return JsonResponse({"status": "success"})
    return JsonResponse({"status": "error"}, status=400)


@login_required
def job_create(request):
  """Đăng tin mới: Ưu tiên trừ tin trong gói, nếu hết gói thì trừ tin miễn phí"""
  if not getattr(request.user, "is_recruiter", False):
    return redirect("home")

  # Lấy hoặc tạo tài khoản quản lý gói của nhà tuyển dụng
  profile_account, _ = RecruiterAccount.objects.get_or_create(user=request.user)

  # Kiểm tra xem gói có còn hạn và đang được kích hoạt không
  now = timezone.now()
  
  # Lấy số lượt còn lại an toàn (nếu model chưa có trường posts_remaining thì mặc định là 999 hoặc check theo hạn)
  posts_remaining = getattr(profile_account, "posts_remaining", 0)
  
  # Điều kiện hợp lệ: Gói đang active AND có hạn sử dụng > hiện tại
  # (Bỏ điều kiện bắt buộc posts_remaining > 0 ở đây nếu admin duyệt theo gói thời gian, 
  # hoặc nếu có dùng posts_remaining thì đảm bảo lúc admin duyệt đã cộng dồn số lượt)
  is_package_valid = (
      profile_account.is_package_active
      and profile_account.package_expires_at
      and profile_account.package_expires_at > now
  )

  has_free_post = profile_account.free_posts_left > 0

  # Nếu gói không hợp lệ và cũng hết tin miễn phí -> Chuyển hướng sang trang mua gói
  if not is_package_valid and not has_free_post:
    messages.warning(
        request,
        "Bạn đã dùng hết lượt đăng tin miễn phí và gói cước hiện tại đã hết hạn"
        " hoặc chưa được kích hoạt. Vui lòng mua gói cước để tiếp tục đăng tin tuyển dụng!",
    )
    return redirect("buy_package")

  if request.method == "POST":
    form = JobForm(request.POST)
    if form.is_valid():
      job = form.save(commit=False)
      job.recruiter = request.user
      job.save()

      # Logic trừ lượt đăng: Ưu tiên trừ gói trước, hết gói trừ tin miễn phí
      if is_package_valid and posts_remaining > 0:
        profile_account.posts_remaining -= 1
        # Nếu dùng hết số lượt trong gói thì có thể tắt cờ active
        if profile_account.posts_remaining <= 0:
          profile_account.is_package_active = False
        profile_account.save()

        messages.success(
            request,
            f"Đăng tin thành công bằng gói cước! Bạn còn lại "
            f"{profile_account.posts_remaining} lượt đăng trong gói.",
        )
      elif is_package_valid:
        # Trường hợp gói tính theo thời gian không giới hạn số tin cụ thể
        messages.success(
            request,
            "Đăng tin thành công bằng gói cước hiện tại của bạn!",
        )
      elif has_free_post:
        profile_account.free_posts_left -= 1
        profile_account.save()
        messages.success(
            request,
            f"Đăng tin thành công bằng lượt tin miễn phí! Bạn còn lại "
            f"{profile_account.free_posts_left} lượt miễn phí.",
        )

      return redirect("recruiter_job_list")
  else:
    form = JobForm()

  return render(
      request,
      "jobs/job_form.html",
      {
          "form": form,
          "has_free_post": has_free_post,
          "has_active_package": is_package_valid,
          "profile_account": profile_account,
      },
  )


@login_required
def job_clone(request, pk):
    """Nhân bản tin tuyển dụng cũ: Cũng kiểm tra quyền đăng tin (ưu tiên gói cước rồi đến miễn phí)"""
    if not getattr(request.user, "is_recruiter", False):
        return redirect("home")

    source_job = get_object_or_404(Job, pk=pk, recruiter=request.user)
    profile_account, _ = RecruiterAccount.objects.get_or_create(user=request.user)

    has_active_package = profile_account.is_package_active
    has_free_post = profile_account.free_posts_left > 0

    if not has_active_package and not has_free_post:
        messages.warning(
            request,
            "Bạn đã hết tin miễn phí và gói cước. Vui lòng mua gói để nhân bản và đăng tin mới!",
        )
        return redirect("buy_package")

    if request.method == "POST":
        form = JobForm(request.POST)
        if form.is_valid():
            new_job = form.save(commit=False)
            new_job.pk = None
            new_job.recruiter = request.user
            new_job.save()

            if has_active_package:
                profile_account.posts_remaining -= 1
                profile_account.save()
            elif has_free_post:
                profile_account.free_posts_left -= 1
                profile_account.save()

            messages.success(
                request, "Tạo tin tuyển dụng mới từ tin cũ thành công!"
            )
            return redirect("recruiter_job_list")
    else:
        form = JobForm(instance=source_job)

    return render(
        request,
        "jobs/job_form.html",
        {"form": form, "job": None, "is_clone": True, "clone_source": source_job},
    )


@login_required
def buy_package_view(request):
    """View cho nhà tuyển dụng chọn mua gói và upload bill chuyển khoản"""
    if not getattr(request.user, "is_recruiter", False):
        return redirect("home")

    packages = SubscriptionPackage.objects.all()
    profile_account, _ = RecruiterAccount.objects.get_or_create(user=request.user)

    if request.method == "POST":
        package_id = request.POST.get("package_id")
        proof_image = request.FILES.get("proof_image")

        selected_package = get_object_or_404(SubscriptionPackage, id=package_id)

        if not proof_image:
            messages.error(request, "Vui lòng tải lên ảnh chụp biên lai chuyển khoản!")
            return redirect("buy_package")

        PackageTransaction.objects.create(
            recruiter=request.user,
            package=selected_package,
            amount=selected_package.price,
            proof_image=proof_image,
            status="pending",
        )

        messages.success(
            request,
            "Gửi yêu cầu mua gói thành công! Admin sẽ kiểm tra và kích hoạt gói của bạn sớm.",
        )
        return redirect("recruiter_job_list")

    return render(
        request,
        "jobs/buy_package.html",
        {"packages": packages, "profile_account": profile_account},
    )


@login_required
def job_edit(request, pk):
    job = get_object_or_404(Job, pk=pk, recruiter=request.user)

    if request.method == "POST":
        form = JobForm(request.POST, instance=job)
        if form.is_valid():
            form.save()
            messages.success(request, "Cập nhật tin tuyển dụng thành công!")
            return redirect("recruiter_job_list")
    else:
        form = JobForm(instance=job)
    return render(request, "jobs/job_form.html", {"form": form, "job": job})


@login_required
def job_delete(request, pk):
    job = get_object_or_404(Job, pk=pk, recruiter=request.user)
    if request.method == "POST":
        job.delete()
        messages.success(request, "Xóa tin tuyển dụng thành công!")
        return redirect("recruiter_job_list")
    return render(request, "jobs/job_confirm_delete.html", {"job": job})


def job_detail(request, pk):
    job = get_object_or_404(Job, pk=pk)
    return render(request, "jobs/job_detail.html", {"job": job})

def all_approved_candidates_view(request):
    # Lọc tất cả các ứng viên có trạng thái đã duyệt thuộc các job của nhà tuyển dụng đang đăng nhập
    # Bạn thay 'approved' hoặc 'Đã duyệt' bằng giá trị status thực tế trong database của bạn
    approved_list = Application.objects.filter(
        job__recruiter=request.user, 
        status='approved' 
    ).select_related('job', 'candidate')
    
    context = {
        'approved_list': approved_list
    }
    return render(request, 'jobs/all_approved_candidates.html', context)