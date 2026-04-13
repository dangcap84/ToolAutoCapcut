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

pyinstaller --noconfirm --clean --onefile --windowed --paths . --hidden-import cli --hidden-import project_loader --hidden-import media_index --hidden-import duration_probe --hidden-import timeline_sync --hidden-import project_writer --name capcut_gui_v2.7 gui.py

if not exist D:\capcut_adapter_test mkdir D:\capcut_adapter_test
copy /Y "%cd%\dist\capcut_gui_v2.7.exe" "D:\capcut_adapter_test\capcut_gui_v2.7.exe" >nul

echo.
echo Build done. EXE path:
echo D:\capcut_adapter_test\capcut_gui_v2.7.exe
pause
