from __future__ import annotations

import ctypes
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


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
