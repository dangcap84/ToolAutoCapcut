# CapCut Adapter MVP (CLI)

Tool sync duration ảnh scene theo voice trong project CapCut Desktop bằng cách sửa trực tiếp JSON draft.

## Scope v1
- 1 video track chính
- 1 audio track chính (nếu có)
- mapping scene theo số trong tên file
- backup trước khi ghi

## Files
- `cli.py`
- `project_loader.py`
- `media_index.py`
- `duration_probe.py`
- `timeline_sync.py`
- `project_writer.py`

## Usage
```bash
cd capcut_adapter
python3 cli.py \
  --project "C:\\Users\\Admin\\AppData\\Local\\CapCut\\User Data\\Projects\\com.lveditor.draft\\Test" \
  --images "D:\\path\\Image\\Test" \
  --voices "D:\\path\\Voice\\Test" \
  --mode inspect
```

Sync:
```bash
python3 cli.py \
  --project "..." \
  --images "..." \
  --voices "..." \
  --mode sync \
  --backup
```

## GUI (Tkinter MVP)
This repo includes a lightweight GUI wrapper (`gui.py`) for running the CLI.

### Run on VPS/Linux (test)
```bash
cd /home/ubuntu/.openclaw/workspace-builder/capcut_adapter_test/capcut_adapter_test/capcut_adapter_transfer
python3 gui.py
```

Notes:
- The GUI uses `python3` to run `cli.py`, so the venv/requirements should be installed.
- On Linux, the default CapCut project root is Windows-only and will show "not found". Use Browse to set the project path manually.

### Windows usage (copy/pack later)
- Copy the repo to Windows, then run:
```powershell
python gui.py
```
- Default project root is:
  `C:\Users\Admin\AppData\Local\CapCut\User Data\Projects\com.lveditor.draft`
- Packaging idea: bundle `gui.py` + `cli.py` with PyInstaller (GUI mode, no console) and ensure `ffprobe` is available in PATH if you use audio durations.

## Notes
- Project CapCut phải đóng trước khi chạy sync.
- Với mp3/m4a cần có `ffprobe` trong PATH để đọc duration.
- Tool sẽ fail rõ nếu mismatch số lượng hoặc index scene/voice.
