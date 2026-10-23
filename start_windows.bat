@echo off
REM Start Payslip Manager on this PC (Windows). Opens http://127.0.0.1:8501
cd /d "%~dp0"
if not exist config\admin.json (
  echo No admin account yet - creating one first.
  python scripts\set_admin.py
)
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
pause
