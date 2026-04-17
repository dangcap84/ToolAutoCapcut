from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Protocol

_CREATE_NO_WINDOW = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


@dataclass
class WindowPolicy:
    """Chuẩn hoá cửa sổ CapCut trước khi thao tác click/OCR."""

    mode: str = "maximize"  # maximize | fixed
    width: int = 1920
    height: int = 1080


@dataclass
class CapCutLaunchResult:
    process_id: int | None
    hwnd: int | None
    exe_path: str | None


@dataclass
class WindowRect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)


class CapCutSessionController:
    """Lifecycle helper cho luồng auto-export dựa trên UI automation.

    Mục tiêu:
    - Kill sạch CapCut cũ để lấy state project mới nhất.
    - Mở CapCut mới.
    - Chuẩn hoá cửa sổ để layout ổn định cho bước nhận diện nút.

    Ghi chú: Module này chỉ chạy trên Windows (ctypes/user32).
    """

    def __init__(self, *, title_hint: str = "CapCut") -> None:
        self.title_hint = title_hint.lower().strip() or "capcut"

    @staticmethod
    def _is_windows() -> bool:
        return hasattr(ctypes, "windll")

    @staticmethod
    def close_existing(timeout_seconds: float = 8.0) -> None:
        """Đóng các process CapCut bằng taskkill (best effort)."""
        if not CapCutSessionController._is_windows():
            return

        names = ["CapCut.exe", "CapCut", "capcut.exe", "capcut"]
        for name in names:
            subprocess.run(
                ["taskkill", "/F", "/IM", name, "/T"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                creationflags=_CREATE_NO_WINDOW,
            )

        time.sleep(max(0.0, timeout_seconds))

    def launch(self, exe_candidates: Iterable[str], timeout_seconds: float = 25.0) -> CapCutLaunchResult:
        """Mở CapCut từ danh sách path candidates, trả về hwnd nếu tìm thấy."""
        if not self._is_windows():
            return CapCutLaunchResult(process_id=None, hwnd=None, exe_path=None)

        for candidate in exe_candidates:
            p = Path(candidate)
            if not p.exists():
                continue

            proc = subprocess.Popen(
                [str(p)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_CREATE_NO_WINDOW,
            )
            deadline = time.time() + max(1.0, timeout_seconds)
            hwnd = None
            while time.time() < deadline:
                hwnd = self.find_main_window(preferred_pid=proc.pid)
                if hwnd:
                    return CapCutLaunchResult(process_id=proc.pid, hwnd=hwnd, exe_path=str(p))
                time.sleep(0.5)
            # thử candidate khác nếu launch nhưng không có window phù hợp

        return CapCutLaunchResult(process_id=None, hwnd=None, exe_path=None)

    def find_main_window(self, preferred_pid: int | None = None) -> int | None:
        """Tìm hwnd của CapCut theo title hint, ưu tiên đúng PID vừa launch.

        Đồng thời loại trừ PID hiện tại để tránh match nhầm cửa sổ tool (CapCut Sync ...).
        """
        if not self._is_windows():
            return None

        user32 = ctypes.windll.user32
        preferred_windows: list[int] = []
        fallback_windows: list[int] = []
        current_pid = int(os.getpid())

        enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def _callback(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True

            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True

            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = (buff.value or "").strip().lower()
            if self.title_hint not in title:
                return True

            pid_ref = ctypes.wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_ref))
            pid = int(pid_ref.value or 0)

            if pid == current_pid:
                return True

            if preferred_pid and pid == int(preferred_pid):
                preferred_windows.append(hwnd)
            else:
                fallback_windows.append(hwnd)
            return True

        user32.EnumWindows(enum_proc_type(_callback), 0)
        if preferred_windows:
            return preferred_windows[0]
        return fallback_windows[0] if fallback_windows else None

    @staticmethod
    def apply_window_policy(hwnd: int, policy: WindowPolicy) -> bool:
        """Đưa cửa sổ về maximize hoặc fixed size. Return True nếu thao tác được."""
        if not CapCutSessionController._is_windows() or not hwnd:
            return False

        user32 = ctypes.windll.user32
        SW_RESTORE = 9
        SW_MAXIMIZE = 3

        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.2)

        mode = (policy.mode or "maximize").strip().lower()
        if mode == "maximize":
            user32.ShowWindow(hwnd, SW_MAXIMIZE)
            user32.SetForegroundWindow(hwnd)
            return True

        # fixed mode
        HWND_TOP = 0
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        ok = user32.SetWindowPos(
            hwnd,
            HWND_TOP,
            0,
            0,
            int(max(640, policy.width)),
            int(max(480, policy.height)),
            SWP_NOZORDER | SWP_NOACTIVATE,
        )
        user32.SetForegroundWindow(hwnd)
        return bool(ok)


class UIBackend(Protocol):
    """UI backend tối thiểu cho bước điều hướng/export project."""

    def hotkey(self, *keys: str) -> None: ...

    def press(self, key: str) -> None: ...

    def write(self, text: str) -> None: ...

    def click_abs(self, x: int, y: int, clicks: int = 1) -> None: ...

    def locate_center_on_screen(self, image_path: str, confidence: float = 0.82) -> tuple[int, int] | None: ...

    def screenshot(self, path: str) -> None: ...


class PyAutoGUIBackend:
    """Backend mặc định bằng pyautogui (optional dependency).

    Nếu môi trường chưa có pyautogui, constructor sẽ raise RuntimeError
    với hướng dẫn cài đặt rõ ràng.
    """

    def __init__(self, pause_seconds: float = 0.05) -> None:
        try:
            import pyautogui  # type: ignore
        except Exception as exc:  # pragma: no cover - runtime dep
            raise RuntimeError(
                "pyautogui is required for UI navigation. Install with: pip install pyautogui"
            ) from exc

        self._pg = pyautogui
        self._pg.PAUSE = max(0.0, float(pause_seconds))

    def hotkey(self, *keys: str) -> None:
        self._pg.hotkey(*keys)

    def press(self, key: str) -> None:
        self._pg.press(key)

    def write(self, text: str) -> None:
        self._pg.write(text)

    def click_abs(self, x: int, y: int, clicks: int = 1) -> None:
        self._pg.click(int(x), int(y), clicks=max(1, int(clicks)))

    def locate_center_on_screen(self, image_path: str, confidence: float = 0.82) -> tuple[int, int] | None:
        try:
            box = self._pg.locateOnScreen(str(image_path), confidence=float(confidence), grayscale=True)
        except Exception:
            return None
        if not box:
            return None
        center = self._pg.center(box)
        return int(center.x), int(center.y)

    def screenshot(self, path: str) -> None:
        self._pg.screenshot(str(path))


@dataclass
class ProjectNavigationConfig:
    """Config điều hướng project trong home/list view của CapCut.

    result_click_x_ratio/y_ratio là toạ độ tương đối trong cửa sổ CapCut
    để click item đầu tiên trong list sau khi search.
    """

    result_click_x_ratio: float = 0.23
    result_click_y_ratio: float = 0.30
    esc_reset_count: int = 2
    after_open_wait_seconds: float = 2.5
    after_search_wait_seconds: float = 1.3
    retries: int = 3
    result_open_clicks: int = 3
    result_fallback_y_step_ratio: float = 0.055
    require_project_title_match: bool = True
    allow_title_change_fallback: bool = True


@dataclass
class ProjectNavigationResult:
    success: bool
    project_name: str
    attempts: int
    message: str
    steps: list[str] = field(default_factory=list)


class ProjectNavigator:
    """Task 2: tìm và mở project theo tên trong giao diện CapCut."""

    def __init__(self, backend: UIBackend, cfg: ProjectNavigationConfig | None = None) -> None:
        self.backend = backend
        self.cfg = cfg or ProjectNavigationConfig()

    @staticmethod
    def _get_window_rect(hwnd: int) -> WindowRect | None:
        if not hasattr(ctypes, "windll") or not hwnd:
            return None

        user32 = ctypes.windll.user32
        rect = ctypes.wintypes.RECT()  # type: ignore[attr-defined]
        ok = user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if not ok:
            return None
        return WindowRect(rect.left, rect.top, rect.right, rect.bottom)

    def _click_project_result_slot(self, hwnd: int) -> bool:
        rect = self._get_window_rect(hwnd)
        if rect is None or rect.width <= 0 or rect.height <= 0:
            return False

        x = int(rect.left + rect.width * self.cfg.result_click_x_ratio)
        base_y = int(rect.top + rect.height * self.cfg.result_click_y_ratio)
        y_step = int(max(8, rect.height * self.cfg.result_fallback_y_step_ratio))

        # thử vài vị trí theo trục dọc để bám vào item thật sự trong list
        candidates = [base_y, base_y + y_step, base_y - y_step]
        for y in candidates:
            self.backend.click_abs(x, y, clicks=max(1, int(self.cfg.result_open_clicks)))
            time.sleep(0.2)
            # fallback bàn phím: nhiều build CapCut mở project ổn hơn bằng Enter
            self.backend.press("enter")
            time.sleep(0.15)

        return True

    @staticmethod
    def _get_window_title(hwnd: int) -> str:
        if not hasattr(ctypes, "windll") or not hwnd:
            return ""
        user32 = ctypes.windll.user32
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        return (buff.value or "").strip()

    def open_project(self, hwnd: int, project_name: str) -> ProjectNavigationResult:
        name = (project_name or "").strip()
        if not name:
            return ProjectNavigationResult(
                success=False,
                project_name=project_name,
                attempts=0,
                message="project_name is empty",
                steps=["validate:empty_project_name"],
            )

        steps: list[str] = []
        last_title = ""
        for attempt in range(1, max(1, self.cfg.retries) + 1):
            try:
                steps.append(f"attempt#{attempt}:reset_to_home")
                for _ in range(max(1, self.cfg.esc_reset_count)):
                    self.backend.press("esc")
                    time.sleep(0.15)

                before_title = self._get_window_title(hwnd)
                if before_title:
                    steps.append(f"attempt#{attempt}:title_before={before_title}")

                steps.append(f"attempt#{attempt}:open_search")
                self.backend.hotkey("ctrl", "f")
                time.sleep(0.15)
                self.backend.hotkey("ctrl", "a")
                self.backend.press("backspace")
                self.backend.write(name)
                self.backend.press("enter")
                time.sleep(max(0.3, self.cfg.after_search_wait_seconds))

                steps.append(f"attempt#{attempt}:open_first_result")
                if not self._click_project_result_slot(hwnd):
                    return ProjectNavigationResult(
                        success=False,
                        project_name=name,
                        attempts=attempt,
                        message="cannot resolve CapCut window rect for result click",
                        steps=steps,
                    )

                time.sleep(max(0.3, self.cfg.after_open_wait_seconds))
                after_title = self._get_window_title(hwnd)
                last_title = after_title or last_title
                if after_title:
                    steps.append(f"attempt#{attempt}:title_after={after_title}")

                # Guard: tránh báo success giả khi click không mở được project.
                if self.cfg.require_project_title_match:
                    n = name.lower()
                    bt = (before_title or "").lower()
                    at = (after_title or "").lower()
                    title_has_project = bool(n and at and n in at)
                    title_changed = bool(at and bt and at != bt and "capcut" in at)

                    if title_has_project or (self.cfg.allow_title_change_fallback and title_changed):
                        steps.append(f"attempt#{attempt}:project_opened_verified")
                        return ProjectNavigationResult(
                            success=True,
                            project_name=name,
                            attempts=attempt,
                            message="project navigation done",
                            steps=steps,
                        )

                    steps.append(f"attempt#{attempt}:project_open_not_verified")
                    continue

                steps.append(f"attempt#{attempt}:project_opened_wait_done")
                return ProjectNavigationResult(
                    success=True,
                    project_name=name,
                    attempts=attempt,
                    message="project navigation done",
                    steps=steps,
                )
            except Exception as exc:  # pragma: no cover - runtime UI branch
                steps.append(f"attempt#{attempt}:error={exc}")
                time.sleep(0.4)

        fail_msg = "project navigation failed after retries"
        if last_title:
            fail_msg += f"; last_title={last_title}"
        return ProjectNavigationResult(
            success=False,
            project_name=name,
            attempts=max(1, self.cfg.retries),
            message=fail_msg,
            steps=steps,
        )


@dataclass
class ExportActionConfig:
    """Task 3: tìm/bấm nút Export + xác nhận popup theo toạ độ fallback.

    export_btn_x_ratio/y_ratio: vị trí nút Export chính trong màn editor.
    confirm_btn_x_ratio/y_ratio: vị trí nút xác nhận Export trong popup.
    """

    export_btn_x_ratio: float = 0.93
    export_btn_y_ratio: float = 0.06
    confirm_btn_x_ratio: float = 0.83
    confirm_btn_y_ratio: float = 0.90
    search_retries: int = 3
    click_retries: int = 2
    post_export_wait_seconds: float = 1.0
    post_confirm_wait_seconds: float = 1.2
    template_confidence: float = 0.82
    export_button_template: str | None = None
    confirm_button_template: str | None = None


@dataclass
class ExportActionResult:
    success: bool
    attempts: int
    message: str
    steps: list[str] = field(default_factory=list)


class ExportActionRunner:
    """Task 3 runner cho bước bấm Export."""

    def __init__(self, backend: UIBackend, cfg: ExportActionConfig | None = None) -> None:
        self.backend = backend
        self.cfg = cfg or ExportActionConfig()

    @staticmethod
    def _get_window_rect(hwnd: int) -> WindowRect | None:
        if not hasattr(ctypes, "windll") or not hwnd:
            return None

        user32 = ctypes.windll.user32
        rect = ctypes.wintypes.RECT()
        ok = user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if not ok:
            return None
        return WindowRect(rect.left, rect.top, rect.right, rect.bottom)

    def _click_ratio(self, hwnd: int, x_ratio: float, y_ratio: float, *, clicks: int = 1) -> bool:
        rect = self._get_window_rect(hwnd)
        if rect is None or rect.width <= 0 or rect.height <= 0:
            return False

        x = int(rect.left + rect.width * min(0.99, max(0.01, x_ratio)))
        y = int(rect.top + rect.height * min(0.99, max(0.01, y_ratio)))
        self.backend.click_abs(x, y, clicks=clicks)
        return True

    def _try_click_template(self, template_path: str | None) -> bool:
        if not template_path:
            return False
        p = Path(template_path)
        if not p.exists():
            return False
        pos = self.backend.locate_center_on_screen(str(p), confidence=self.cfg.template_confidence)
        if not pos:
            return False
        self.backend.click_abs(pos[0], pos[1], clicks=1)
        return True

    def trigger_export(self, hwnd: int) -> ExportActionResult:
        steps: list[str] = []

        for attempt in range(1, max(1, self.cfg.search_retries) + 1):
            try:
                steps.append(f"attempt#{attempt}:focus_editor")
                self.backend.press("esc")
                time.sleep(0.15)

                steps.append(f"attempt#{attempt}:click_export")
                export_clicked = False
                for click_attempt in range(1, max(1, self.cfg.click_retries) + 1):
                    if self._try_click_template(self.cfg.export_button_template):
                        export_clicked = True
                        steps.append(f"attempt#{attempt}:export_clicked_template#{click_attempt}")
                        break

                    if self._click_ratio(
                        hwnd,
                        self.cfg.export_btn_x_ratio,
                        self.cfg.export_btn_y_ratio,
                        clicks=1,
                    ):
                        export_clicked = True
                        steps.append(f"attempt#{attempt}:export_clicked_ratio#{click_attempt}")
                        break
                    time.sleep(0.2)

                if not export_clicked:
                    steps.append(f"attempt#{attempt}:export_click_failed")
                    continue

                time.sleep(max(0.2, self.cfg.post_export_wait_seconds))

                # xác nhận popup (nếu có)
                steps.append(f"attempt#{attempt}:confirm_export")
                confirmed = False
                for click_attempt in range(1, max(1, self.cfg.click_retries) + 1):
                    if self._try_click_template(self.cfg.confirm_button_template):
                        confirmed = True
                        steps.append(f"attempt#{attempt}:confirm_clicked_template#{click_attempt}")
                        break

                    if self._click_ratio(
                        hwnd,
                        self.cfg.confirm_btn_x_ratio,
                        self.cfg.confirm_btn_y_ratio,
                        clicks=1,
                    ):
                        confirmed = True
                        steps.append(f"attempt#{attempt}:confirm_clicked_ratio#{click_attempt}")
                        break

                    time.sleep(0.2)

                # Popup có thể không xuất hiện (CapCut auto start export), nên không ép fail.
                if not confirmed:
                    steps.append(f"attempt#{attempt}:confirm_not_found_continue")

                time.sleep(max(0.3, self.cfg.post_confirm_wait_seconds))
                return ExportActionResult(
                    success=True,
                    attempts=attempt,
                    message="export action triggered",
                    steps=steps,
                )

            except Exception as exc:  # pragma: no cover - runtime UI branch
                steps.append(f"attempt#{attempt}:error={exc}")
                time.sleep(0.3)

        return ExportActionResult(
            success=False,
            attempts=max(1, self.cfg.search_retries),
            message="failed to trigger export",
            steps=steps,
        )


@dataclass
class ExportProgressConfig:
    """Task 4: theo dõi tiến trình export tới 100%/done."""

    timeout_seconds: float = 60.0 * 6.0
    poll_interval_seconds: float = 2.0
    done_template: str | None = None
    progress_100_template: str | None = None
    export_panel_template: str | None = None
    template_confidence: float = 0.82
    max_wait_without_template_seconds: float = 8.0


@dataclass
class ExportProgressResult:
    success: bool
    reached_done: bool
    elapsed_seconds: float
    message: str
    steps: list[str] = field(default_factory=list)


class ExportProgressWatcher:
    """Watcher cho bước chờ export hoàn tất.

    Hiện tại dùng template detection là chính; nếu chưa có template,
    watcher vẫn chờ timeout theo polling để orchestration không vỡ.
    """

    def __init__(self, backend: UIBackend, cfg: ExportProgressConfig | None = None) -> None:
        self.backend = backend
        self.cfg = cfg or ExportProgressConfig()

    def _seen_template(self, template_path: str | None) -> bool:
        if not template_path:
            return False
        p = Path(template_path)
        if not p.exists():
            return False
        pos = self.backend.locate_center_on_screen(str(p), confidence=self.cfg.template_confidence)
        return bool(pos)

    def wait_until_done(self) -> ExportProgressResult:
        steps: list[str] = []
        start = time.time()
        deadline = start + max(5.0, self.cfg.timeout_seconds)
        has_any_template = bool(self.cfg.done_template or self.cfg.progress_100_template or self.cfg.export_panel_template)

        while time.time() < deadline:
            elapsed = time.time() - start
            steps.append(f"poll@{elapsed:.1f}s")

            if self._seen_template(self.cfg.done_template):
                steps.append("done_template_detected")
                return ExportProgressResult(
                    success=True,
                    reached_done=True,
                    elapsed_seconds=elapsed,
                    message="export completed (done template)",
                    steps=steps,
                )

            if self._seen_template(self.cfg.progress_100_template):
                steps.append("progress_100_template_detected")
                return ExportProgressResult(
                    success=True,
                    reached_done=True,
                    elapsed_seconds=elapsed,
                    message="export reached 100%",
                    steps=steps,
                )

            if self.cfg.export_panel_template:
                panel_visible = self._seen_template(self.cfg.export_panel_template)
                steps.append(f"panel_visible={int(panel_visible)}")

            # Không có template thì fail rất sớm để user thấy lỗi rõ ngay,
            # tránh cảm giác treo hoặc đợi quá lâu.
            if (not has_any_template) and elapsed >= max(3.0, self.cfg.max_wait_without_template_seconds):
                return ExportProgressResult(
                    success=False,
                    reached_done=False,
                    elapsed_seconds=elapsed,
                    message="missing progress templates; cannot verify export completion",
                    steps=steps,
                )

            time.sleep(max(0.2, self.cfg.poll_interval_seconds))

        elapsed = time.time() - start
        return ExportProgressResult(
            success=False,
            reached_done=False,
            elapsed_seconds=elapsed,
            message="export progress timeout",
            steps=steps,
        )


@dataclass
class BatchProjectResult:
    project_name: str
    success: bool
    stage: str
    message: str
    elapsed_seconds: float
    steps: list[str] = field(default_factory=list)


@dataclass
class BatchExportConfig:
    project_names: list[str]
    window_policy: WindowPolicy = field(default_factory=WindowPolicy)
    relaunch_each_project: bool = True
    launch_timeout_seconds: float = 25.0
    close_wait_seconds: float = 3.0
    screenshot_on_fail_dir: str | None = None


class BatchExportRunner:
    """Task 4 orchestration: open project -> export -> wait done -> close -> next."""

    def __init__(
        self,
        *,
        session: CapCutSessionController,
        navigator: ProjectNavigator,
        exporter: ExportActionRunner,
        watcher: ExportProgressWatcher,
        backend: UIBackend,
        exe_candidates: Iterable[str] | None = None,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        self.session = session
        self.navigator = navigator
        self.exporter = exporter
        self.watcher = watcher
        self.backend = backend
        self.exe_candidates = list(exe_candidates or default_capcut_exe_candidates())
        self.logger = logger or (lambda _msg: None)

    def _log(self, msg: str) -> None:
        self.logger(msg)

    def _capture_fail_shot(self, out_dir: str | None, project_name: str, stage: str) -> str | None:
        if not out_dir:
            return None
        try:
            p = Path(out_dir)
            p.mkdir(parents=True, exist_ok=True)
            ts = int(time.time())
            safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in project_name)
            shot = p / f"{safe}_{stage}_{ts}.png"
            self.backend.screenshot(str(shot))
            return str(shot)
        except Exception:
            return None

    def _launch_and_prepare(self, cfg: BatchExportConfig) -> CapCutLaunchResult:
        self.session.close_existing(timeout_seconds=cfg.close_wait_seconds)
        launch = self.session.launch(self.exe_candidates, timeout_seconds=cfg.launch_timeout_seconds)
        if launch.hwnd:
            self.session.apply_window_policy(launch.hwnd, cfg.window_policy)
            time.sleep(0.8)
        return launch

    def run(self, cfg: BatchExportConfig) -> list[BatchProjectResult]:
        results: list[BatchProjectResult] = []

        for idx, project_name in enumerate(cfg.project_names, start=1):
            t0 = time.time()
            name = (project_name or "").strip()
            if not name:
                results.append(
                    BatchProjectResult(
                        project_name=project_name,
                        success=False,
                        stage="validate",
                        message="empty project name",
                        elapsed_seconds=0.0,
                    )
                )
                continue

            self._log(f"[{idx}/{len(cfg.project_names)}] start project={name}")

            launch = self._launch_and_prepare(cfg)
            if not launch.hwnd:
                elapsed = time.time() - t0
                shot = self._capture_fail_shot(cfg.screenshot_on_fail_dir, name, "launch")
                msg = "cannot launch CapCut window"
                if shot:
                    msg += f"; screenshot={shot}"
                results.append(
                    BatchProjectResult(
                        project_name=name,
                        success=False,
                        stage="launch",
                        message=msg,
                        elapsed_seconds=elapsed,
                    )
                )
                continue

            nav = self.navigator.open_project(launch.hwnd, name)
            if not nav.success:
                elapsed = time.time() - t0
                shot = self._capture_fail_shot(cfg.screenshot_on_fail_dir, name, "navigate")
                msg = nav.message + (f"; screenshot={shot}" if shot else "")
                results.append(
                    BatchProjectResult(
                        project_name=name,
                        success=False,
                        stage="navigate",
                        message=msg,
                        elapsed_seconds=elapsed,
                        steps=nav.steps,
                    )
                )
                self.session.close_existing(timeout_seconds=cfg.close_wait_seconds)
                continue

            act = self.exporter.trigger_export(launch.hwnd)
            if not act.success:
                elapsed = time.time() - t0
                shot = self._capture_fail_shot(cfg.screenshot_on_fail_dir, name, "export_click")
                msg = act.message + (f"; screenshot={shot}" if shot else "")
                results.append(
                    BatchProjectResult(
                        project_name=name,
                        success=False,
                        stage="export_click",
                        message=msg,
                        elapsed_seconds=elapsed,
                        steps=nav.steps + act.steps,
                    )
                )
                self.session.close_existing(timeout_seconds=cfg.close_wait_seconds)
                continue

            prog = self.watcher.wait_until_done()
            elapsed = time.time() - t0
            if not prog.success:
                shot = self._capture_fail_shot(cfg.screenshot_on_fail_dir, name, "progress_timeout")
                msg = prog.message + (f"; screenshot={shot}" if shot else "")
                results.append(
                    BatchProjectResult(
                        project_name=name,
                        success=False,
                        stage="progress",
                        message=msg,
                        elapsed_seconds=elapsed,
                        steps=nav.steps + act.steps + prog.steps,
                    )
                )
                self.session.close_existing(timeout_seconds=cfg.close_wait_seconds)
                continue

            results.append(
                BatchProjectResult(
                    project_name=name,
                    success=True,
                    stage="done",
                    message=prog.message,
                    elapsed_seconds=elapsed,
                    steps=nav.steps + act.steps + prog.steps,
                )
            )
            self._log(f"[{idx}/{len(cfg.project_names)}] done project={name} in {elapsed:.1f}s")

            if cfg.relaunch_each_project:
                self.session.close_existing(timeout_seconds=cfg.close_wait_seconds)

        return results


def default_capcut_exe_candidates() -> list[str]:
    """Common CapCut executable locations on Windows."""
    user = Path.home()
    appdata_local = user / "AppData" / "Local"
    candidates = [
        appdata_local / "CapCut" / "Apps" / "CapCut.exe",
        appdata_local / "CapCut" / "CapCut.exe",
        Path("C:/Program Files/CapCut/CapCut.exe"),
        Path("C:/Program Files (x86)/CapCut/CapCut.exe"),
    ]
    return [str(p) for p in candidates]
