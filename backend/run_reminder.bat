@echo off
cd /d D:\hc\tuyendungvieclam\backend
call venv\Scripts\activate
python manage.py send_interview_reminders
pause