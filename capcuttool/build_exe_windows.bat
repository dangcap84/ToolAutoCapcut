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

if exist "%cd%\transition_effect_pack.zip" del /f /q "%cd%\transition_effect_pack.zip"
if exist "%cd%\transition_effect_pack" powershell -NoProfile -Command "Compress-Archive -Path '%cd%\transition_effect_pack\*' -DestinationPath '%cd%\transition_effect_pack.zip' -Force" >nul

if exist "%cd%\mask_background_pack.zip" del /f /q "%cd%\mask_background_pack.zip"
if exist "%cd%\mask_background_pack" powershell -NoProfile -Command "Compress-Archive -Path '%cd%\mask_background_pack\*' -DestinationPath '%cd%\mask_background_pack.zip' -Force" >nul

pyinstaller --noconfirm --clean --onefile --windowed --paths . --add-data "transition_effect_pack.zip;." --add-data "mask_background_pack.zip;." --hidden-import cli --hidden-import project_loader --hidden-import media_index --hidden-import duration_probe --hidden-import timeline_sync --hidden-import project_writer --hidden-import transition_tools --hidden-import builtin_transition_catalog --hidden-import keyframe_tools --hidden-import mask_tools --hidden-import mask_library --name capcut_gui_v3.9.13 gui.py

if not exist D:\capcut_adapter_test mkdir D:\capcut_adapter_test
copy /Y "%cd%\dist\capcut_gui_v3.9.13.exe" "D:\capcut_adapter_test\capcut_gui_v3.9.13.exe" >nul

echo.
echo Build done. EXE path:
echo D:\capcut_adapter_test\capcut_gui_v3.9.13.exe
echo Transition pack is embedded inside EXE.
pause
