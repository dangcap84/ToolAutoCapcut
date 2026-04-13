$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (!(Test-Path .venv)) {
  py -3 -m venv .venv
}

. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

pyinstaller --noconfirm --clean --onefile --windowed --paths . --hidden-import cli --hidden-import project_loader --hidden-import media_index --hidden-import duration_probe --hidden-import timeline_sync --hidden-import project_writer --name capcut_gui_v2.9 gui.py

$targetDir = 'D:\capcut_adapter_test'
$targetExe = Join-Path $targetDir 'capcut_gui_v2.9.exe'
if (!(Test-Path $targetDir)) {
  New-Item -ItemType Directory -Path $targetDir | Out-Null
}
Copy-Item "$PSScriptRoot\dist\capcut_gui_v2.9.exe" $targetExe -Force

Write-Host "Build done. EXE path: $targetExe"
