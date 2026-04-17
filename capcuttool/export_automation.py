from __future__ import annotations

import ctypes
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Protocol


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

            proc = subprocess.Popen([str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.time() + max(1.0, timeout_seconds)
            hwnd = None
            while time.time() < deadline:
                hwnd = self.find_main_window()
                if hwnd:
                    return CapCutLaunchResult(process_id=proc.pid, hwnd=hwnd, exe_path=str(p))
                time.sleep(0.5)
            # thử candidate khác nếu launch nhưng không có window phù hợp

        return CapCutLaunchResult(process_id=None, hwnd=None, exe_path=None)

    def find_main_window(self) -> int | None:
        """Tìm hwnd của CapCut theo title hint."""
        if not self._is_windows():
            return None

        user32 = ctypes.windll.user32
        windows: list[int] = []

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
            if self.title_hint in title:
                windows.append(hwnd)
            return True

        user32.EnumWindows(enum_proc_type(_callback), 0)
        return windows[0] if windows else None

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
    """UI backend tối thiểu cho bước điều hướng project."""

    def hotkey(self, *keys: str) -> None: ...

    def press(self, key: str) -> None: ...

    def write(self, text: str) -> None: ...

    def click_abs(self, x: int, y: int, clicks: int = 1) -> None: ...


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


@dataclass
class ProjectNavigationConfig:
    """Config điều hướng project trong home/list view của CapCut.

    result_click_x_ratio/y_ratio là toạ độ tương đối trong cửa sổ CapCut
    để click item đầu tiên trong list sau khi search.
    """

    result_click_x_ratio: float = 0.23
    result_click_y_ratio: float = 0.30
    esc_reset_count: int = 2
    after_open_wait_seconds: float = 2.0
    after_search_wait_seconds: float = 1.1
    retries: int = 2


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
        y = int(rect.top + rect.height * self.cfg.result_click_y_ratio)
        self.backend.click_abs(x, y, clicks=2)
        return True

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
        for attempt in range(1, max(1, self.cfg.retries) + 1):
            try:
                steps.append(f"attempt#{attempt}:reset_to_home")
                for _ in range(max(1, self.cfg.esc_reset_count)):
                    self.backend.press("esc")
                    time.sleep(0.15)

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

        return ProjectNavigationResult(
            success=False,
            project_name=name,
            attempts=max(1, self.cfg.retries),
            message="project navigation failed after retries",
            steps=steps,
        )


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
