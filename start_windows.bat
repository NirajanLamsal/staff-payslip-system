@echo off
REM Start Payslip Manager on this PC (Windows). Opens http://127.0.0.1:8501
cd /d "%~dp0"
if exist .env goto run_app
if exist config\admin.json goto run_app
if defined PAYSLIP_ADMIN_USER if defined PAYSLIP_ADMIN_HASH goto run_app
echo No admin account yet - creating one first.
python scripts\set_admin.py
:run_app
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
pause
