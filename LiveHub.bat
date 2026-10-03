@echo off
rem ============================================================
rem  Kaynt LiveHub - file chay DUY NHAT
rem  Lan dau: tu tao .venv (Python 3.11) + cai thu vien.
rem  Sau do: mo cua so Kaynt LiveHub (nut Bat dau / Dung).
rem  Them tham so "console" de chay kieu cu (cua so den):  LiveHub.bat console
rem ============================================================
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Dang tao moi truong ao .venv - Python 3.11 ...
  py -3.11 -m venv .venv || (echo Khong tim thay Python 3.11. Cai tu https://www.python.org/downloads/release/python-3119/ & pause & exit /b 1)
  del /q .venv\.installed 2>nul
)
fc /b requirements.txt .venv\.installed >nul 2>&1 || (
  echo Dang cai thu vien, lan dau hoi lau ...
  .venv\Scripts\python.exe -m pip install --upgrade pip
  .venv\Scripts\python.exe -m pip install -r requirements.txt || (echo Cai thu vien that bai & pause & exit /b 1)
  copy /y requirements.txt .venv\.installed >nul
)
if /i "%~1"=="console" (
  .venv\Scripts\python.exe app.py
  pause
  exit /b
)
start "" .venv\Scripts\pythonw.exe launcher.pyw
