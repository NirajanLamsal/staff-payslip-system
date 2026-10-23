@echo off
REM Create or change the admin account (Windows)
cd /d "%~dp0"
python scripts\set_admin.py %*
pause
