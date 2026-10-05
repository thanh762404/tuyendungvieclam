@echo off
pushd "%~dp0"
"%~dp0venv\Scripts\python.exe" manage.py send_interview_reminders
set "RESULT=%ERRORLEVEL%"
popd
exit /b %RESULT%