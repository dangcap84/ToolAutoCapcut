@echo off
setlocal

REM Build CapCut Adapter EXE on Windows
REM Prereq: Python 3.11+ installed and in PATH

cd /d %~dp0

if not exist .venv (
  py -3 -m venv .venv
)

call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt

pyinstaller --noconfirm --clean --onefile --windowed --name capcut_gui_v10 gui.py

if not exist C:\Users\Admin\capcut_adapter_test mkdir C:\Users\Admin\capcut_adapter_test
copy /Y "%cd%\dist\capcut_gui_v10.exe" "C:\Users\Admin\capcut_adapter_test\capcut_gui_v10.exe" >nul

echo.
echo Build done. EXE path:
echo C:\Users\Admin\capcut_adapter_test\capcut_gui_v10.exe
pause
