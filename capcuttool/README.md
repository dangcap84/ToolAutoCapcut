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

Sync + thêm transition ngẫu nhiên:
```bash
python3 cli.py \
  --project "..." \
  --images "..." \
  --voices "..." \
  --mode sync \
  --transition-mode random \
  --transition-effects "6864867302936941064,7406274848898583813"
```

Ghi chú transition:
- Tool thêm transition vào `materials.transitions` và gắn ref transition vào `extra_material_refs` của từng segment video (từ segment thứ 2 trở đi).
- `--transition-effects` để trống => random từ toàn bộ catalog tìm thấy trong cache CapCut + fallback từ project mẫu.
- Có thể override đường dẫn cache bằng `--transition-effect-cache-root`.

## GUI (Tkinter MVP)
This repo includes a lightweight GUI wrapper (`gui.py`) for running the CLI.

## Auto Export (WIP skeleton)
A new helper module `export_automation.py` has been added to prepare reliable UI-based export flow on Windows.
Current scope (step-by-step foundation):
- Close existing CapCut instances (`taskkill`) for clean state.
- Launch CapCut from common executable paths.
- Detect CapCut main window by title hint.
- Normalize window state (maximize or fixed-size policy).
- Navigate project by name (Ctrl+F search + open first result slot with configurable coordinates).

Implemented classes:
- `CapCutSessionController`
- `ProjectNavigator` + `ProjectNavigationConfig`
- `ExportActionRunner` + `ExportActionConfig`
- `ExportProgressWatcher` + `ExportProgressConfig`
- `BatchExportRunner` + `BatchExportConfig`
- `PyAutoGUIBackend` (optional runtime dependency)

Export trigger strategy (Task 3):
- Try template match click first (`export_button_template`, `confirm_button_template`) if template images are provided.
- Fallback to ratio-based click in the CapCut window when templates are unavailable.
- Confirm popup is best-effort (if not found, continue because some CapCut variants auto-start export).

Progress/loop strategy (Task 4):
- Poll export completion by template detection (`done_template` or `progress_100_template`) with timeout.
- Orchestrate per project: relaunch CapCut -> open project -> trigger export -> wait done -> close/relaunch next.
- Save failure screenshots optionally via `screenshot_on_fail_dir`.

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
