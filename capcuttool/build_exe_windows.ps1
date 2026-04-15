$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (!(Test-Path .venv)) {
  py -3 -m venv .venv
}

. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

$embeddedZip = Join-Path $PSScriptRoot 'transition_effect_pack.zip'
$packSrc = Join-Path $PSScriptRoot 'transition_effect_pack'
if (Test-Path $embeddedZip) {
  Remove-Item -Force $embeddedZip
}
if (Test-Path $packSrc) {
  Compress-Archive -Path "$packSrc\*" -DestinationPath $embeddedZip -Force
}

$maskZip = Join-Path $PSScriptRoot 'mask_background_pack.zip'
$maskPackSrc = Join-Path $PSScriptRoot 'mask_background_pack'
if (Test-Path $maskZip) {
  Remove-Item -Force $maskZip
}
if (Test-Path $maskPackSrc) {
  Compress-Archive -Path "$maskPackSrc\*" -DestinationPath $maskZip -Force
}

pyinstaller --noconfirm --clean --onefile --windowed --paths . --add-data "transition_effect_pack.zip;." --add-data "mask_background_pack.zip;." --hidden-import cli --hidden-import project_loader --hidden-import media_index --hidden-import duration_probe --hidden-import timeline_sync --hidden-import project_writer --hidden-import transition_tools --hidden-import builtin_transition_catalog --hidden-import keyframe_tools --hidden-import mask_tools --hidden-import mask_library --name capcut_gui_v3.9.11 gui.py

$targetDir = 'D:\capcut_adapter_test'
$targetExe = Join-Path $targetDir 'capcut_gui_v3.9.11.exe'
if (!(Test-Path $targetDir)) {
  New-Item -ItemType Directory -Path $targetDir | Out-Null
}
Copy-Item "$PSScriptRoot\dist\capcut_gui_v3.9.11.exe" $targetExe -Force

Write-Host "Build done. EXE path: $targetExe"
Write-Host "Transition pack is embedded inside EXE."
