#!/usr/bin/env python3
"""Tkinter/ttk GUI wrapper for the CapCut adapter CLI."""

from __future__ import annotations

import contextlib
import io
import json
import queue
import shutil
import subprocess
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk
from tkinter import EW, NSEW, filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from cli import run_sync

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CAPCUT_PROJECT_ROOT = Path(
    "C:/Users/Admin/AppData/Local/CapCut/User Data/Projects/com.lveditor.draft"
)
STATUS_COLORS = {
    "info": "#334155",
    "success": "#16a34a",
    "warning": "#f59e0b",
    "error": "#ef4444",
}
TEMPLATE_CACHE_DIR = BASE_DIR / "_template_cache"
TEMPLATE_CACHE_PROJECT_DIR = TEMPLATE_CACHE_DIR / "project_template"
TEMPLATE_CACHE_META = TEMPLATE_CACHE_DIR / "template_meta.json"
TEMPLATE_SOURCE_DIR = BASE_DIR / "_template_source"
TEMPLATE_SOURCE_PROJECT_DIR = TEMPLATE_SOURCE_DIR / "project_template"
TEMPLATE_SOURCE_META = TEMPLATE_SOURCE_DIR / "template_meta.json"

# UI palette inspired by tool33ai
ACCENT = "#7c3aed"
ACCENT_2 = "#06b6d4"
BG = "#0b1020"
PANEL = "#121a2b"
PANEL_2 = "#172036"
TEXT = "#e5eefc"
SUBTEXT = "#94a3b8"


class CapCutGui:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("CapCut Sync v2.4")
        self.root.geometry("1180x760")
        self.root.minsize(1024, 680)
        self.root.configure(background=BG)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.style = ttk.Style(self.root)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.style.configure("AppTitle.TLabel", font=("Segoe UI Semibold", 18), foreground=TEXT, background=BG)
        self.style.configure("SectionTitle.TLabel", font=("Segoe UI Semibold", 11), foreground=TEXT, background=PANEL)
        self.style.configure("Subtle.TLabel", font=("Segoe UI", 9), foreground=SUBTEXT, background=PANEL)
        self.style.configure("ProjectCard.TLabelframe", padding=10, background=PANEL, foreground=TEXT)
        self.style.configure("ProjectCard.TLabelframe.Label", font=("Segoe UI Semibold", 10), foreground=TEXT, background=PANEL)
        self.style.configure("Panel.TFrame", background=PANEL)
        self.style.configure("Header.TFrame", background=BG)
        self.style.configure(
            "Project.TCheckbutton",
            font=("Segoe UI", 10),
            foreground=TEXT,
            background=PANEL_2,
        )
        self.style.map(
            "Project.TCheckbutton",
            background=[("active", PANEL_2)],
            foreground=[("disabled", SUBTEXT)],
        )
        self.style.configure(
            "Accent.TButton",
            font=("Segoe UI Semibold", 10),
            foreground=TEXT,
            background=ACCENT,
            padding=(12, 6),
        )
        self.style.map(
            "Accent.TButton",
            background=[("active", "#6d28d9"), ("disabled", "#334155")],
            foreground=[("disabled", SUBTEXT)],
        )
        self.style.configure(
            "Secondary.TButton",
            font=("Segoe UI Semibold", 10),
            foreground=TEXT,
            background=PANEL_2,
            padding=(12, 6),
        )
        self.style.configure(
            "Ghost.TButton",
            font=("Segoe UI", 9),
            foreground=SUBTEXT,
            background=PANEL_2,
            padding=(10, 4),
        )
        self.style.map(
            "Ghost.TButton",
            foreground=[("active", TEXT), ("disabled", "#64748b")],
            background=[("active", "#24314f"), ("disabled", PANEL_2)],
        )
        self.style.configure(
            "Search.TEntry",
            fieldbackground="#0f172a",
            foreground=TEXT,
            insertcolor=TEXT,
            borderwidth=1,
            padding=6,
        )
        self.style.map(
            "Secondary.TButton",
            background=[("active", "#1f2a44"), ("disabled", "#1f2a44")],
            foreground=[("disabled", SUBTEXT)],
        )
        self.style.configure(
            "Badge.TLabel",
            font=("Segoe UI Semibold", 9),
            foreground=TEXT,
            background="{info}",
            padding=(10, 4),
        )
        self.style.configure(
            "Status.TLabel",
            font=("Consolas", 10),
            foreground=TEXT,
            background=BG,
        )
        self.style.configure(
            "Accent.Horizontal.TProgressbar",
            troughcolor=PANEL_2,
            background=ACCENT,
            thickness=12,
        )

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.current_process: subprocess.Popen | None = None
        self.current_task_running = False
        self.current_action = "sync"

        # Keep vars for internal compatibility/fallback, but UI remains grid-first.
        self.images_var = tk.StringVar()
        self.voices_var = tk.StringVar()
        self.mode_var = tk.StringVar(value="sync")
        self.backup_var = tk.BooleanVar(value=True)
        self.batch_voices_root_var = tk.StringVar()
        self.batch_media_root_var = tk.StringVar()
        self.template_info_var = tk.StringVar(value="Template cache: chưa lưu")
        self.status_var = tk.StringVar(value="Sẵn sàng · Bấm Làm mới, chọn dự án rồi Đồng bộ")

        self.project_items: list[tuple[str, str, tk.BooleanVar, ttk.Checkbutton]] = []
        self.project_stats_var = tk.StringVar(value="Đã chọn 0/0 dự án")

        self.projects_canvas: tk.Canvas | None = None
        self.projects_container: ttk.Frame | None = None
        self.projects_canvas_window: int | None = None
        self.projects_scroll: ttk.Scrollbar | None = None
        self.refresh_button: ttk.Button | None = None
        self.sync_button: ttk.Button | None = None
        self.batch_button: ttk.Button | None = None
        self.progress_bar: ttk.Progressbar | None = None
        self.status_badge: ttk.Label | None = None
        self.status_label: ttk.Label | None = None

        self._build_layout()
        self._wire_events()
        self._refresh_template_info_label()

        self.root.after(100, self._flush_log)
        self.refresh_projects()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_layout(self) -> None:
        main_frame = ttk.Frame(self.root, padding=18, style="Header.TFrame")
        main_frame.grid(row=0, column=0, sticky=NSEW)
        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=2)
        main_frame.rowconfigure(1, weight=1)

        header = ttk.Frame(main_frame, padding=(0, 0, 0, 12), style="Header.TFrame")
        header.grid(row=0, column=0, columnspan=2, sticky=EW)
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="Đồng bộ dự án CapCut", style="AppTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="Làm mới danh sách → chọn dự án → Đồng bộ",
            style="Subtle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        left_panel = ttk.Frame(main_frame, style="Panel.TFrame")
        left_panel.grid(row=1, column=0, sticky=NSEW, padx=(0, 14))
        left_panel.columnconfigure(0, weight=1)
        left_panel.rowconfigure(2, weight=1)

        action_card = ttk.Labelframe(
            left_panel,
            text="Thao tác",
            padding=14,
            style="ProjectCard.TLabelframe",
        )
        action_card.grid(row=0, column=0, sticky=EW)
        action_card.columnconfigure(1, weight=1)

        ttk.Label(action_card, text="Thao tác", style="SectionTitle.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        ttk.Label(
            action_card,
            text="Đồng bộ dự án đã chọn hoặc tạo batch từ thư mục voice/video-image.",
            style="Subtle.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 12))

        self.refresh_button = ttk.Button(
            action_card,
            text="Làm mới",
            command=self.refresh_projects,
            width=12,
            style="Secondary.TButton",
        )
        self.refresh_button.grid(row=2, column=0, sticky="w")

        self.sync_button = ttk.Button(
            action_card,
            text="Đồng bộ",
            command=self._on_sync_audio,
            width=12,
            style="Accent.TButton",
        )
        self.sync_button.grid(row=2, column=1, sticky="w", padx=(8, 0))

        ttk.Label(
            action_card,
            text=f"Thư mục dự án CapCut: {DEFAULT_CAPCUT_PROJECT_ROOT}",
            style="Subtle.TLabel",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))

        batch_card = ttk.Labelframe(
            left_panel,
            text="Tạo dự án hàng loạt",
            padding=12,
            style="ProjectCard.TLabelframe",
        )
        batch_card.grid(row=1, column=0, sticky=EW, pady=(12, 0))
        batch_card.columnconfigure(1, weight=1)

        ttk.Label(batch_card, text="Thư mục voice:", style="Subtle.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 6))
        ttk.Entry(batch_card, textvariable=self.batch_voices_root_var, style="Search.TEntry").grid(row=0, column=1, sticky=EW, pady=(0, 6))
        ttk.Button(batch_card, text="Chọn", style="Ghost.TButton", command=self._pick_batch_voices_root, width=8).grid(row=0, column=2, padx=(8, 0), pady=(0, 6))

        ttk.Label(batch_card, text="Thư mục video/image:", style="Subtle.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(batch_card, textvariable=self.batch_media_root_var, style="Search.TEntry").grid(row=1, column=1, sticky=EW)
        ttk.Button(batch_card, text="Chọn", style="Ghost.TButton", command=self._pick_batch_media_root, width=8).grid(row=1, column=2, padx=(8, 0))

        self.batch_button = ttk.Button(
            batch_card,
            text="Tạo batch",
            command=self._on_create_batch_projects,
            style="Secondary.TButton",
            width=12,
        )
        self.batch_button.grid(row=2, column=0, sticky="w", pady=(10, 0))

        ttk.Label(
            batch_card,
            textvariable=self.template_info_var,
            style="Subtle.TLabel",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))

        projects_card = ttk.Labelframe(
            left_panel,
            text="Danh sách dự án",
            padding=12,
            style="ProjectCard.TLabelframe",
        )
        projects_card.grid(row=2, column=0, sticky=NSEW, pady=(14, 0))
        projects_card.columnconfigure(0, weight=1)
        projects_card.rowconfigure(1, weight=1)

        ttk.Label(
            projects_card,
            textvariable=self.project_stats_var,
            style="Subtle.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        list_host = ttk.Frame(projects_card, style="Panel.TFrame")
        list_host.grid(row=1, column=0, sticky=NSEW)
        list_host.columnconfigure(0, weight=1)
        list_host.rowconfigure(0, weight=1)

        self.projects_canvas = tk.Canvas(
            list_host,
            background=PANEL_2,
            highlightthickness=0,
            bd=0,
        )
        self.projects_canvas.grid(row=0, column=0, sticky=NSEW)
        self.projects_scroll = ttk.Scrollbar(list_host, orient="vertical", command=self.projects_canvas.yview)
        self.projects_scroll.grid(row=0, column=1, sticky="ns")
        self.projects_canvas.configure(yscrollcommand=self.projects_scroll.set)

        self.projects_container = ttk.Frame(self.projects_canvas, style="Panel.TFrame")
        self.projects_canvas_window = self.projects_canvas.create_window(
            (0, 0),
            window=self.projects_container,
            anchor="nw",
        )

        right_panel = ttk.Frame(main_frame, style="Panel.TFrame")
        right_panel.grid(row=1, column=1, sticky=NSEW)
        right_panel.columnconfigure(0, weight=1)
        right_panel.rowconfigure(0, weight=1)

        log_card = ttk.Labelframe(
            right_panel,
            text="Nhật ký chạy",
            padding=12,
            style="ProjectCard.TLabelframe",
        )
        log_card.grid(row=0, column=0, sticky=NSEW)
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(1, weight=1)

        ttk.Label(
            log_card,
            text="Hiển thị log đồng bộ và lỗi (nếu có).",
            style="Subtle.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.log_text = ScrolledText(
            log_card,
            height=18,
            wrap="none",
            font=("Consolas", 10),
        )
        self.log_text.grid(row=1, column=0, sticky=NSEW)
        self.log_text.configure(
            state="disabled",
            background="#0b1220",
            foreground=TEXT,
            padx=10,
            pady=10,
        )

        status_card = ttk.Frame(main_frame, padding=(0, 12, 0, 0), style="Header.TFrame")
        status_card.grid(row=2, column=0, columnspan=2, sticky=EW, pady=(12, 0))
        status_card.columnconfigure(1, weight=1)

        self.status_badge = ttk.Label(status_card, text="THÔNG TIN", style="Badge.TLabel")
        self.status_badge.grid(row=0, column=0, sticky="w")

        self.status_label = ttk.Label(
            status_card,
            textvariable=self.status_var,
            style="Status.TLabel",
        )
        self.status_label.grid(row=0, column=1, sticky="ew", padx=(10, 12))

        self.progress_bar = ttk.Progressbar(status_card, mode="indeterminate", style="Accent.Horizontal.TProgressbar")
        self.progress_bar.grid(row=0, column=2, sticky="ew")
        status_card.columnconfigure(2, weight=1)

    def _wire_events(self) -> None:
        if self.projects_canvas is not None:
            self.projects_canvas.bind("<Configure>", self._on_projects_canvas_configure)
            self.projects_canvas.bind_all("<MouseWheel>", self._on_projects_mousewheel)
        if self.projects_container is not None:
            self.projects_container.bind("<Configure>", self._on_projects_container_configure)

    def _on_projects_canvas_configure(self, event) -> None:
        if self.projects_canvas is None or self.projects_canvas_window is None:
            return
        self.projects_canvas.itemconfigure(self.projects_canvas_window, width=event.width)

    def _on_projects_container_configure(self, _event=None) -> None:
        if self.projects_canvas is None:
            return
        self.projects_canvas.configure(scrollregion=self.projects_canvas.bbox("all"))

    def _on_projects_mousewheel(self, event) -> str:
        if self.projects_canvas is None:
            return "break"
        delta = -1 if event.delta > 0 else 1
        self.projects_canvas.yview_scroll(delta, "units")
        return "break"

    def _toggle_project(self) -> None:
        self._update_project_stats()

    def _update_project_stats(self) -> None:
        total = len(self.project_items)
        selected = sum(1 for _, _, var, _ in self.project_items if var.get())
        self.project_stats_var.set(f"Đã chọn {selected}/{total} dự án")

    def _collect_selected_projects(self) -> list[str]:
        out: list[str] = []
        for path, _, var, _ in self.project_items:
            if var.get():
                out.append(path)
        return sorted(out)

    def _pick_batch_voices_root(self) -> None:
        path = filedialog.askdirectory(title="Chọn thư mục voice")
        if path:
            self.batch_voices_root_var.set(path)

    def _pick_batch_media_root(self) -> None:
        path = filedialog.askdirectory(title="Chọn thư mục video/image")
        if path:
            self.batch_media_root_var.set(path)

    def _list_child_dirs(self, root: Path) -> list[Path]:
        if not root.exists() or not root.is_dir():
            return []
        return sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.name.lower())

    def _ensure_unique_project_dir(self, base_name: str) -> Path:
        safe_name = base_name.strip() or "project_moi"
        target = DEFAULT_CAPCUT_PROJECT_ROOT / safe_name
        if not target.exists():
            return target
        idx = 2
        while True:
            alt = DEFAULT_CAPCUT_PROJECT_ROOT / f"{safe_name}_{idx}"
            if not alt.exists():
                return alt
            idx += 1

    def _replace_folder_with_files(self, dst_dir: Path, src_dir: Path) -> None:
        if dst_dir.exists():
            shutil.rmtree(dst_dir)
        dst_dir.mkdir(parents=True, exist_ok=True)
        for item in sorted(src_dir.iterdir(), key=lambda p: p.name.lower()):
            if item.is_file():
                shutil.copy2(item, dst_dir / item.name)

    def _refresh_template_info_label(self) -> None:
        if TEMPLATE_SOURCE_META.exists():
            try:
                meta = json.loads(TEMPLATE_SOURCE_META.read_text(encoding="utf-8"))
                source = meta.get("source", "?")
                saved_at = meta.get("saved_at", "?")
                self.template_info_var.set(f"Template nội bộ: nguồn '{source}' · cập nhật {saved_at}")
                return
            except Exception:
                pass

        if TEMPLATE_CACHE_META.exists():
            try:
                meta = json.loads(TEMPLATE_CACHE_META.read_text(encoding="utf-8"))
                source = meta.get("source", "?")
                saved_at = meta.get("saved_at", "?")
                self.template_info_var.set(f"Template cache tạm: từ '{source}' · {saved_at}")
                return
            except Exception:
                pass

        self.template_info_var.set("Template: chưa có dữ liệu")

    def _save_template_cache(self, source_project: Path) -> None:
        TEMPLATE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if TEMPLATE_CACHE_PROJECT_DIR.exists():
            shutil.rmtree(TEMPLATE_CACHE_PROJECT_DIR)
        shutil.copytree(source_project, TEMPLATE_CACHE_PROJECT_DIR)
        meta = {
            "source": source_project.name,
            "source_path": str(source_project),
            "saved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }
        TEMPLATE_CACHE_META.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._refresh_template_info_label()

    def _find_auto_template_source(self) -> Path:
        selected_projects = self._collect_selected_projects()
        if selected_projects:
            return Path(selected_projects[0])

        fallback = DEFAULT_CAPCUT_PROJECT_ROOT / "test"
        if fallback.exists() and fallback.is_dir():
            return fallback

        if DEFAULT_CAPCUT_PROJECT_ROOT.exists() and DEFAULT_CAPCUT_PROJECT_ROOT.is_dir():
            for entry in sorted(DEFAULT_CAPCUT_PROJECT_ROOT.iterdir(), key=lambda p: p.name.lower()):
                if not entry.is_dir():
                    continue
                name_lower = entry.name.lower()
                if "cloud" in name_lower or "recycle" in name_lower:
                    continue
                if name_lower in {
                    "$recycle.bin",
                    ".recycle_bin",
                    "recycle bin",
                    "recycle",
                    "recycle.bin",
                    "system volume information",
                    "projects",
                    "project",
                }:
                    continue
                if (entry / "draft_content.json").exists():
                    return entry

        raise ValueError(
            "Không có project nào để học template. Chỉ cần mở CapCut có 1 project bất kỳ rồi chạy lại."
        )

    def _resolve_template_project(self) -> Path:
        if TEMPLATE_SOURCE_PROJECT_DIR.exists() and TEMPLATE_SOURCE_PROJECT_DIR.is_dir():
            return TEMPLATE_SOURCE_PROJECT_DIR

        if TEMPLATE_CACHE_PROJECT_DIR.exists() and TEMPLATE_CACHE_PROJECT_DIR.is_dir():
            return TEMPLATE_CACHE_PROJECT_DIR

        source = self._find_auto_template_source()
        self._save_template_cache(source)
        self.log_queue.put(f"[TEMPLATE] Auto-cache từ {source}\n")
        return TEMPLATE_CACHE_PROJECT_DIR

    def _build_batch_jobs(self, voices_root: Path, media_root: Path) -> list[tuple[str, Path, Path]]:
        voice_children = self._list_child_dirs(voices_root)
        media_children = self._list_child_dirs(media_root)

        has_subfolders = bool(voice_children or media_children)
        if not has_subfolders:
            return [(voices_root.name or "project_moi", voices_root, media_root)]

        media_map = {p.name.lower(): p for p in media_children}
        jobs: list[tuple[str, Path, Path]] = []
        for v in voice_children:
            m = media_map.get(v.name.lower())
            if m is None:
                self.log_queue.put(f"[BATCH] Bỏ qua '{v.name}' vì không có thư mục media trùng tên.\n")
                continue
            jobs.append((v.name, v, m))

        if not jobs:
            raise ValueError("Không tìm thấy cặp thư mục con trùng tên giữa voice và video/image.")
        return jobs

    def _on_create_batch_projects(self) -> None:
        if self.current_process is not None or self.current_task_running:
            messagebox.showwarning("Đang bận", "Đang có tiến trình chạy. Vui lòng chờ xong.")
            return

        voices_root = Path(self.batch_voices_root_var.get().strip())
        media_root = Path(self.batch_media_root_var.get().strip())

        if not voices_root.exists() or not voices_root.is_dir():
            messagebox.showerror("Thiếu thư mục", "Thư mục voice không hợp lệ.")
            return
        if not media_root.exists() or not media_root.is_dir():
            messagebox.showerror("Thiếu thư mục", "Thư mục video/image không hợp lệ.")
            return

        try:
            template_project = self._resolve_template_project()
        except Exception as exc:
            messagebox.showerror("Thiếu template", str(exc))
            return

        if (
            template_project == TEMPLATE_CACHE_PROJECT_DIR
            and not TEMPLATE_SOURCE_PROJECT_DIR.exists()
        ):
            try:
                TEMPLATE_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
                if TEMPLATE_SOURCE_PROJECT_DIR.exists():
                    shutil.rmtree(TEMPLATE_SOURCE_PROJECT_DIR)
                shutil.copytree(TEMPLATE_CACHE_PROJECT_DIR, TEMPLATE_SOURCE_PROJECT_DIR)
                if TEMPLATE_CACHE_META.exists():
                    cache_meta = json.loads(TEMPLATE_CACHE_META.read_text(encoding="utf-8"))
                else:
                    cache_meta = {
                        "source": "auto",
                        "source_path": str(TEMPLATE_CACHE_PROJECT_DIR),
                        "saved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    }
                TEMPLATE_SOURCE_META.write_text(
                    json.dumps(cache_meta, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                self._refresh_template_info_label()
                self._append_log("[TEMPLATE] Đã lưu template nội bộ vào source code.\n")
            except Exception as exc:
                messagebox.showwarning("Lưu template nội bộ lỗi", str(exc))

        self.current_action = "batch_create"
        self._append_log("\n--- Tạo batch project ---\n")
        self._append_log(
            f"template={template_project}\nvoices_root={voices_root}\nmedia_root={media_root}\n"
        )
        self._set_status("Đang tạo project hàng loạt từ template...", "info")
        self._set_running_state(True)
        self.current_task_running = True

        threading.Thread(
            target=self._execute_batch_create,
            args=(template_project, voices_root, media_root),
            daemon=True,
        ).start()

    def _execute_batch_create(self, template_project: Path, voices_root: Path, media_root: Path) -> None:
        output_buf = io.StringIO()
        overall_code = 0
        try:
            jobs = self._build_batch_jobs(voices_root, media_root)
            with contextlib.redirect_stdout(output_buf):
                print(f"batch_jobs={len(jobs)}")
                for idx, (name, v_dir, m_dir) in enumerate(jobs, start=1):
                    new_project = self._ensure_unique_project_dir(name)
                    print(f"--- batch {idx}/{len(jobs)}: {name} ---")
                    print(f"template={template_project}")
                    print(f"new_project={new_project}")
                    shutil.copytree(template_project, new_project)

                    images_dir = new_project / "images"
                    voices_dir = new_project / "voices"
                    self._replace_folder_with_files(images_dir, m_dir)
                    self._replace_folder_with_files(voices_dir, v_dir)

                    print(f"images={images_dir}")
                    print(f"voices={voices_dir}")
                    print(f"created_project={new_project}")
        except Exception:
            output_buf.write(traceback.format_exc())
            overall_code = 1

        out = output_buf.getvalue()
        if out:
            self.log_queue.put(out)
        self.log_queue.put(f"PROCESS_EXIT:{overall_code}")
        self.log_queue.put("REFRESH_PROJECTS")

    def _resolve_media_dirs(
        self, project_path: str, images_input: str, voices_input: str
    ) -> tuple[str, str]:
        project = Path(project_path)

        if images_input and voices_input:
            return images_input, voices_input

        image_candidates = [
            project / "images",
            project / "image",
            project / "scene_images",
            project / "scenes",
            project / "media" / "images",
            project / "materials" / "images",
        ]
        voice_candidates = [
            project / "voices",
            project / "voice",
            project / "audio",
            project / "audios",
            project / "media" / "voices",
            project / "materials" / "voices",
        ]

        resolved_images = images_input
        if not resolved_images:
            for path in image_candidates:
                if path.exists() and path.is_dir():
                    resolved_images = str(path)
                    break

        resolved_voices = voices_input
        if not resolved_voices:
            for path in voice_candidates:
                if path.exists() and path.is_dir():
                    resolved_voices = str(path)
                    break

        if not resolved_images or not resolved_voices:
            raise ValueError(
                "Cannot auto-detect image/voice folders inside selected project. "
                "Please set manually once, or create standard folders (images + voices)."
            )

        return resolved_images, resolved_voices

    def _on_sync_audio(self) -> None:
        self.mode_var.set("sync")
        self._start_run()

    def _start_run(self) -> None:
        if self.current_process is not None or self.current_task_running:
            messagebox.showwarning("Busy", "A run is already in progress.")
            return

        images = self.images_var.get().strip()
        voices = self.voices_var.get().strip()
        mode = self.mode_var.get()
        selected_projects = self._collect_selected_projects()

        if not selected_projects:
            messagebox.showerror("Chưa chọn dự án", "Vui lòng chọn ít nhất 1 dự án trong danh sách.")
            return

        try:
            if images and voices and len(selected_projects) == 1:
                images, voices = self._resolve_media_dirs(selected_projects[0], images, voices)
        except Exception as exc:
            messagebox.showerror("Thiếu thư mục media", str(exc))
            return

        self._append_log("\n--- Running CLI task ---\n")
        self._append_log(
            f"mode={mode} projects={len(selected_projects)} images={images or '[auto]'} voices={voices or '[auto]'} backup={self.backup_var.get()}\n"
        )
        self.current_action = "sync"
        self._set_status(f"Đang đồng bộ {len(selected_projects)} dự án đã chọn...", "info")
        self._set_running_state(True)

        if getattr(sys, "frozen", False) or len(selected_projects) > 1:
            self.current_task_running = True
            threading.Thread(
                target=self._execute_embedded_batch,
                args=(selected_projects, images, voices, mode, self.backup_var.get()),
                daemon=True,
            ).start()
            return

        project = selected_projects[0]
        cmd = [
            sys.executable,
            str(BASE_DIR / "cli.py"),
            "--project",
            project,
        ]
        if images:
            cmd.extend(["--images", images])
        if voices:
            cmd.extend(["--voices", voices])
        cmd.extend(["--mode", mode])
        if self.backup_var.get():
            cmd.append("--backup")
        self._append_log("$ " + " ".join(cmd) + "\n")
        threading.Thread(target=self._execute_command, args=(cmd,), daemon=True).start()

    def refresh_projects(self) -> None:
        if self.projects_container is None:
            return

        for child in self.projects_container.winfo_children():
            child.destroy()
        self.project_items = []

        if not DEFAULT_CAPCUT_PROJECT_ROOT.exists():
            self.project_stats_var.set("Đã chọn 0/0 dự án")
            self._append_log(
                f'Không tìm thấy thư mục dự án mặc định "{DEFAULT_CAPCUT_PROJECT_ROOT}".\n'
            )
            self._set_status("Không tìm thấy thư mục dự án CapCut", "warning")
            return

        entries = sorted(item for item in DEFAULT_CAPCUT_PROJECT_ROOT.iterdir() if item.is_dir())
        filtered: list[Path] = []
        skipped = 0
        for entry in entries:
            name_lower = entry.name.lower()
            if "cloud" in name_lower or "recycle" in name_lower:
                skipped += 1
                continue
            if name_lower in {
                "$recycle.bin",
                ".recycle_bin",
                "recycle bin",
                "recycle",
                "recycle.bin",
                "system volume information",
                "projects",
                "project",
            }:
                skipped += 1
                continue
            filtered.append(entry)

        if skipped:
            self._append_log(f"Đã bỏ qua {skipped} thư mục không phải project.\n")

        if not filtered:
            self.project_stats_var.set("Đã chọn 0/0 dự án")
            self._append_log(f"Không tìm thấy dự án CapCut trong {DEFAULT_CAPCUT_PROJECT_ROOT}.\n")
            self._set_status("Không có dự án", "warning")
            return

        for entry in filtered:
            project_var = tk.BooleanVar(value=False)
            label = ttk.Checkbutton(
                self.projects_container,
                text=entry.name,
                variable=project_var,
                style="Project.TCheckbutton",
                onvalue=True,
                offvalue=False,
                command=self._toggle_project,
            )
            self.project_items.append((str(entry), entry.name, project_var, label))

        for row, (_, _, _, label) in enumerate(self.project_items):
            label.grid(row=row, column=0, sticky=EW, pady=(0, 4), padx=(0, 2))

        self._update_project_stats()
        self._set_status(f"Đã làm mới danh sách · sẵn sàng {len(filtered)} dự án", "info")

    def _execute_embedded_batch(
        self, projects: list[str], images: str, voices: str, mode: str, backup: bool
    ) -> None:
        output_buf = io.StringIO()
        overall_code = 0
        try:
            with contextlib.redirect_stdout(output_buf):
                for idx, project in enumerate(projects, start=1):
                    resolved_images = images
                    resolved_voices = voices
                    if images and voices:
                        resolved_images, resolved_voices = self._resolve_media_dirs(
                            project, images, voices
                        )
                    print(f"--- project {idx}/{len(projects)}: {project} ---")
                    print(f"images={resolved_images or '[auto]'}")
                    print(f"voices={resolved_voices or '[auto]'}")
                    code = run_sync(
                        Path(project),
                        Path(resolved_images) if resolved_images else None,
                        Path(resolved_voices) if resolved_voices else None,
                        backup,
                    )
                    if code != 0:
                        overall_code = code
                        break
        except Exception:
            output_buf.write(traceback.format_exc())
            overall_code = 1

        out = output_buf.getvalue()
        if out:
            self.log_queue.put(out)
        self.log_queue.put(f"PROCESS_EXIT:{overall_code}")

    def _execute_command(self, cmd: list[str]) -> None:
        try:
            process = subprocess.Popen(
                cmd,
                cwd=BASE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except Exception as exc:
            self.log_queue.put(f"ERROR: {exc}\n")
            self.log_queue.put("PROCESS_EXIT:1")
            return

        self.current_process = process
        assert process.stdout is not None
        for line in process.stdout:
            self.log_queue.put(line)
        process.wait()
        self.log_queue.put(f"PROCESS_EXIT:{process.returncode}")

    def _flush_log(self) -> None:
        try:
            while True:
                item = self.log_queue.get_nowait()
                if item == "REFRESH_PROJECTS":
                    self.refresh_projects()
                elif item.startswith("PROCESS_EXIT:"):
                    self._on_process_finish(int(item.split(":", 1)[1]))
                else:
                    self._append_log(item)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._flush_log)

    def _on_process_finish(self, return_code: int) -> None:
        self.current_process = None
        self.current_task_running = False
        self._set_running_state(False)

        is_batch = self.current_action == "batch_create"
        success_title = "Tạo batch xong" if is_batch else "Đồng bộ xong"
        success_message = (
            "Đã tạo project hàng loạt thành công."
            if is_batch
            else "Đã đồng bộ các dự án đã chọn thành công."
        )
        error_title = "Tạo batch lỗi" if is_batch else "Đồng bộ lỗi"

        if return_code == 0:
            self._set_status(
                "Tạo batch thành công" if is_batch else "Đồng bộ thành công",
                "success",
            )
            self._show_toast(success_title, success_message, "success")
            messagebox.showinfo(success_title, success_message)
        else:
            self._set_status(
                f"Tạo batch lỗi (mã {return_code})" if is_batch else f"Đồng bộ lỗi (mã {return_code})",
                "error",
            )
            self._show_toast(error_title, f"Tiến trình lỗi với mã {return_code}.", "danger")
            messagebox.showerror(error_title, f"Tiến trình lỗi với mã {return_code}. Xem nhật ký chạy để biết chi tiết.")

        self._append_log(f"\n--- Process exited with code {return_code} ---\n")
        self.current_action = "sync"

    def _set_running_state(self, running: bool) -> None:
        if self.progress_bar is not None:
            if running:
                self.progress_bar.start(10)
            else:
                self.progress_bar.stop()

        new_state = "disabled" if running else "normal"
        if self.sync_button is not None:
            self.sync_button.configure(state=new_state)
        if self.refresh_button is not None:
            self.refresh_button.configure(state=new_state)
        if self.batch_button is not None:
            self.batch_button.configure(state=new_state)

    def _set_status(self, message: str, status_type: str = "info") -> None:
        self.status_var.set(message)
        badge_map = {"info": "THÔNG TIN", "success": "THÀNH CÔNG", "warning": "CẢNH BÁO", "error": "LỖI"}
        badge_text = badge_map.get(status_type, "THÔNG TIN")
        badge_color = STATUS_COLORS.get(status_type, STATUS_COLORS["info"])
        if self.status_badge is not None:
            self.status_badge.configure(text=badge_text, background=badge_color)
        if self.status_label is not None:
            self.status_label.configure(background=BG, foreground=TEXT)

    def _show_toast(self, title: str, message: str, bootstyle: str) -> None:
        # Tkinter-only build: no external toast library.
        return

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, message)
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _on_close(self) -> None:
        if self.current_process:
            if not messagebox.askyesno(
                "Dừng tiến trình?",
                "Đang có tiến trình chạy. Dừng và đóng ứng dụng?",
            ):
                return
            self.current_process.terminate()

        if self.current_task_running:
            if not messagebox.askyesno(
                "Đóng ứng dụng?",
                "Tiến trình vẫn đang chạy. Bạn vẫn muốn đóng không?",
            ):
                return

        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    CapCutGui().run()


if __name__ == "__main__":
    main()
