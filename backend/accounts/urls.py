from django.urls import path
from . import views

urlpatterns = [
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    path('profile/edit/', views.profile_edit_view, name='profile_edit'),
    path('password-reset/', views.password_reset_view, name='password_reset'),
    path('password-reset/confirm/<int:user_id>/', views.password_reset_confirm_view, name='password_reset_confirm'),
]