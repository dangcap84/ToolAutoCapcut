#!/usr/bin/env python3
"""Tkinter/ttk GUI wrapper for the CapCut adapter CLI."""

from __future__ import annotations

import contextlib
import copy
import ctypes
import ctypes.wintypes
import io
import json
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
import math
from pathlib import Path
import tkinter as tk
from tkinter import EW, NSEW, filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from uuid import uuid4

from cli import run_sync
from duration_probe import probe_audio_duration_seconds
from media_index import AUDIO_EXTS, MEDIA_EXTS, VIDEO_EXTS
from timeline_sync import sec_to_us
from project_loader import load_project
from project_writer import write_json_atomic
from transition_tools import (
    apply_random_transitions_to_draft,
    load_transition_catalog,
    seed_effect_cache_from_pack,
    seed_effect_cache_from_zip,
)
from keyframe_tools import apply_zoom_keyframes_to_draft
from mask_tools import apply_mask_to_draft
from mask_library import load_mask_background_library, seed_mask_background_cache
from export_automation import (
    BatchExportConfig,
    BatchExportRunner,
    CapCutSessionController,
    ExportActionConfig,
    ExportActionRunner,
    ExportProgressConfig,
    ExportProgressWatcher,
    ProjectNavigationConfig,
    ProjectNavigator,
    PyAutoGUIBackend,
    WindowPolicy,
    WindowRect,
    default_capcut_exe_candidates,
)

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
TRANSITION_CATALOG_LIMIT = 50
BULK_ACTION_WARNING_THRESHOLD = 5
MASK_BACKGROUND_CATALOG_PATH = BASE_DIR / "mask_background_catalog.json"
MASK_TEMPLATE_PROJECT_NAME = "Test1-mask"

I18N_TEXTS = {
    "vi": {
        "app_title": "CapCut Sync v1.0.14",
        "header_title": "Đồng bộ dự án CapCut",
        "header_subtitle": "Chọn dự án ở bên phải, sau đó chạy thao tác ở các tab chức năng.",
        "language": "Ngôn ngữ",
        "tab_create": "Tạo dự án",
        "tab_sync": "Đồng bộ",
        "tab_export": "Xuất bản",
        "tab_transition": "Chuyển cảnh",
        "tab_keyframe": "Keyframe",
        "tab_mask": "Mask",
        "sync_button": "Đồng bộ",
        "refresh_button": "Làm mới",
        "publish_button": "Xuất bản",
        "test_click_button": "Test click #1",
        "pick_region_button": "Khoanh vùng",
        "projects_group": "Dự án CapCut",
        "projects_selected": "Đã chọn {selected}/{total} dự án",
        "status_ready": "Sẵn sàng · Bấm Làm mới, chọn dự án rồi Đồng bộ",
        "log_group": "Nhật ký chạy",
        "log_subtitle": "Nhật ký thao tác (đồng bộ / chuyển cảnh / keyframe / lỗi).",
    },
    "en": {
        "app_title": "CapCut Sync v1.0.14",
        "header_title": "CapCut Project Sync",
        "header_subtitle": "Select projects on the right, then run actions from feature tabs.",
        "language": "Language",
        "tab_create": "Create",
        "tab_sync": "Sync",
        "tab_export": "Publish",
        "tab_transition": "Transition",
        "tab_keyframe": "Keyframe",
        "tab_mask": "Mask",
        "sync_button": "Sync",
        "refresh_button": "Refresh",
        "publish_button": "Publish",
        "test_click_button": "Test click #1",
        "pick_region_button": "Pick region",
        "projects_group": "CapCut Projects",
        "projects_selected": "Selected {selected}/{total} projects",
        "status_ready": "Ready · Click Refresh, choose projects, then Sync",
        "log_group": "Run Log",
        "log_subtitle": "Execution logs (sync / transition / keyframe / errors).",
    },
}


class CapCutGui:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.ui_lang_var = tk.StringVar(master=self.root, value="vi")
        self.root.title(I18N_TEXTS["vi"]["app_title"])
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
        self.style.configure("AppTitle.TLabel", font=("Segoe UI Semibold", 19), foreground=TEXT, background=BG)
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
            "Transition.TCheckbutton",
            font=("Segoe UI", 9),
            foreground=TEXT,
            background=PANEL_2,
            padding=(0, 0),
        )
        self.style.map(
            "Transition.TCheckbutton",
            background=[("active", PANEL_2)],
            foreground=[("disabled", SUBTEXT)],
        )
        self.style.configure(
            "Accent.TButton",
            font=("Segoe UI Semibold", 10),
            foreground=TEXT,
            background=ACCENT,
            padding=(14, 8),
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
            padding=(12, 8),
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
        self.batch_project_name_var = tk.StringVar()
        self.batch_video_volume_db_var = tk.StringVar(value="0.0")
        self.batch_audio_volume_db_var = tk.StringVar(value="0.0")
        self.template_info_var = tk.StringVar(value="Template cache: chưa lưu")
        self.status_var = tk.StringVar(value=I18N_TEXTS["vi"]["status_ready"])

        self.transition_enable_var = tk.BooleanVar(value=False)
        self.transition_effects_var = tk.StringVar(value="")
        self.transition_catalog: list[dict] = []
        self.transition_check_vars: list[tk.BooleanVar] = []
        self.transition_checks_container: ttk.Frame | None = None
        self.transition_checks_canvas: tk.Canvas | None = None
        self.transition_checks_scroll: tk.Scrollbar | None = None

        self.keyframe_mode_var = tk.StringVar(value="zoom_in")
        self.keyframe_only_picture_var = tk.BooleanVar(value=False)
        self.keyframe_start_percent_var = tk.StringVar(value="100")
        self.keyframe_end_percent_var = tk.StringVar(value="112")
        self.keyframe_full_duration_var = tk.BooleanVar(value=True)
        self.keyframe_duration_seconds_var = tk.StringVar(value="3.0")

        self.mask_mode_var = tk.StringVar(value="params")
        self.mask_overlay_width_var = tk.StringVar(value="1800")
        self.mask_overlay_height_var = tk.StringVar(value="928")
        self.mask_round_corner_var = tk.StringVar(value="20")
        self.mask_scale_percent_var = tk.StringVar(value="90")
        self.mask_backgrounds_var = tk.StringVar(value="")
        self.mask_inputs_params_frame: ttk.Frame | None = None
        self.mask_inputs_ratio_frame: ttk.Frame | None = None
        self.mask_library_catalog: list[dict] = []
        self.mask_library_check_vars: list[tk.BooleanVar] = []
        self.mask_check_all_var = tk.BooleanVar(value=False)
        self.mask_library_container: ttk.Frame | None = None

        # Export list/grid calibration (tỉ lệ theo cửa sổ CapCut: 0..1)
        self.export_list_left_var = tk.StringVar(value="0.08")
        self.export_list_top_var = tk.StringVar(value="0.16")
        self.export_list_width_var = tk.StringVar(value="0.84")
        self.export_list_height_var = tk.StringVar(value="0.76")
        self.export_grid_first_x_var = tk.StringVar(value="0.14")
        self.export_grid_first_y_var = tk.StringVar(value="0.16")
        self.export_grid_gap_x_var = tk.StringVar(value="0.29")
        self.export_grid_gap_y_var = tk.StringVar(value="0.23")

        self.project_items: list[tuple[str, str, tk.BooleanVar, ttk.Checkbutton]] = []
        self.project_stats_var = tk.StringVar(value=I18N_TEXTS["vi"]["projects_selected"].format(selected=0, total=0))

        self.projects_canvas: tk.Canvas | None = None
        self.projects_container: ttk.Frame | None = None
        self.projects_canvas_window: int | None = None
        self.projects_scroll: tk.Scrollbar | None = None
        self.refresh_button: ttk.Button | None = None
        self.export_publish_button: ttk.Button | None = None
        self.test_click_button: ttk.Button | None = None
        self.pick_region_button: ttk.Button | None = None
        self.sync_button: ttk.Button | None = None
        self.batch_button: ttk.Button | None = None
        self.apply_transition_button: ttk.Button | None = None
        self.apply_keyframe_button: ttk.Button | None = None
        self.apply_mask_button: ttk.Button | None = None
        self.progress_bar: ttk.Progressbar | None = None
        self.status_badge: ttk.Label | None = None
        self.status_label: ttk.Label | None = None

        self.header_title_label: ttk.Label | None = None
        self.header_subtitle_label: ttk.Label | None = None
        self.language_label: ttk.Label | None = None
        self.nav_tabs: ttk.Notebook | None = None
        self.projects_card: ttk.Labelframe | None = None
        self.log_card: ttk.Labelframe | None = None
        self.log_subtitle_label: ttk.Label | None = None

        self._build_layout()
        self._wire_events()
        self.ui_lang_var.trace_add("write", lambda *_: self._apply_language())
        self.keyframe_mode_var.trace_add("write", lambda *_: self._on_keyframe_mode_changed())
        self._on_keyframe_mode_changed()
        self._apply_language()
        self._on_mask_mode_changed()
        self._refresh_template_info_label()

        self.root.after(100, self._flush_log)
        self.refresh_projects()
        seeded = seed_effect_cache_from_pack()
        if seeded > 0:
            self._append_log(f"[TRANSITION] seeded_effect_cache_from_pack={seeded}\n")
        self._load_transition_catalog_to_input(show_message=False)
        seeded_mask_bg = seed_mask_background_cache()
        if seeded_mask_bg > 0:
            self._append_log(f"[MASK] seeded_background_pack={seeded_mask_bg}\n")
        self._load_mask_library_to_input(show_message=False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _t(self, key: str, **kwargs) -> str:
        lang = (self.ui_lang_var.get() or "vi").strip().lower()
        if lang not in I18N_TEXTS:
            lang = "vi"
        tmpl = I18N_TEXTS[lang].get(key) or I18N_TEXTS["vi"].get(key) or key
        if kwargs:
            try:
                return tmpl.format(**kwargs)
            except Exception:
                return tmpl
        return tmpl

    def _apply_language(self) -> None:
        self.root.title(self._t("app_title"))

        if self.header_title_label is not None:
            self.header_title_label.configure(text=self._t("header_title"))
        if self.header_subtitle_label is not None:
            self.header_subtitle_label.configure(text=self._t("header_subtitle"))
        if self.language_label is not None:
            self.language_label.configure(text=self._t("language"))

        if self.nav_tabs is not None:
            self.nav_tabs.tab(0, text=self._t("tab_create"))
            self.nav_tabs.tab(1, text=self._t("tab_sync"))
            self.nav_tabs.tab(2, text=self._t("tab_export"))
            self.nav_tabs.tab(3, text=self._t("tab_transition"))
            self.nav_tabs.tab(4, text=self._t("tab_keyframe"))
            self.nav_tabs.tab(5, text=self._t("tab_mask"))

        if self.sync_button is not None:
            self.sync_button.configure(text=self._t("sync_button"))
        if self.refresh_button is not None:
            self.refresh_button.configure(text=self._t("refresh_button"))
        if self.export_publish_button is not None:
            self.export_publish_button.configure(text=self._t("publish_button"))
        if self.test_click_button is not None:
            self.test_click_button.configure(text=self._t("test_click_button"))
        if self.pick_region_button is not None:
            self.pick_region_button.configure(text=self._t("pick_region_button"))

        if self.projects_card is not None:
            self.projects_card.configure(text=self._t("projects_group"))
        if self.log_card is not None:
            self.log_card.configure(text=self._t("log_group"))
        if self.log_subtitle_label is not None:
            self.log_subtitle_label.configure(text=self._t("log_subtitle"))

        self._update_project_stats()

    def _build_layout(self) -> None:
        main_frame = ttk.Frame(self.root, padding=18, style="Header.TFrame")
        main_frame.grid(row=0, column=0, sticky=NSEW)
        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=2)
        main_frame.rowconfigure(1, weight=1)

        header = ttk.Frame(main_frame, padding=(0, 0, 0, 12), style="Header.TFrame")
        header.grid(row=0, column=0, columnspan=2, sticky=EW)
        header.columnconfigure(0, weight=1)

        self.header_title_label = ttk.Label(header, text=self._t("header_title"), style="AppTitle.TLabel")
        self.header_title_label.grid(row=0, column=0, sticky="w")

        self.header_subtitle_label = ttk.Label(
            header,
            text=self._t("header_subtitle"),
            style="Subtle.TLabel",
        )
        self.header_subtitle_label.grid(row=1, column=0, sticky="w", pady=(4, 0))

        lang_row = ttk.Frame(header, style="Header.TFrame")
        lang_row.grid(row=0, column=1, rowspan=2, sticky="e")
        self.language_label = ttk.Label(lang_row, text=self._t("language"), style="Subtle.TLabel")
        self.language_label.grid(row=0, column=0, sticky="e", padx=(0, 6))
        lang_combo = ttk.Combobox(
            lang_row,
            values=["vi", "en"],
            textvariable=self.ui_lang_var,
            state="readonly",
            width=6,
        )
        lang_combo.grid(row=0, column=1, sticky="e")

        left_panel = ttk.Frame(main_frame, style="Panel.TFrame")
        left_panel.grid(row=1, column=0, sticky=NSEW, padx=(0, 14))
        left_panel.columnconfigure(0, weight=1)
        left_panel.rowconfigure(1, weight=1)

        ttk.Label(
            left_panel,
            text="Điều hướng chức năng",
            style="SectionTitle.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        nav_tabs = ttk.Notebook(left_panel)
        nav_tabs.grid(row=1, column=0, sticky=NSEW)
        self.nav_tabs = nav_tabs

        sync_tab = ttk.Frame(nav_tabs, style="Panel.TFrame", padding=10)
        export_tab = ttk.Frame(nav_tabs, style="Panel.TFrame", padding=10)
        create_tab = ttk.Frame(nav_tabs, style="Panel.TFrame", padding=10)
        transition_tab = ttk.Frame(nav_tabs, style="Panel.TFrame", padding=10)
        keyframe_tab = ttk.Frame(nav_tabs, style="Panel.TFrame", padding=10)
        mask_tab = ttk.Frame(nav_tabs, style="Panel.TFrame", padding=10)
        sync_tab.columnconfigure(0, weight=1)
        export_tab.columnconfigure(0, weight=1)
        create_tab.columnconfigure(0, weight=1)
        transition_tab.columnconfigure(0, weight=1)
        transition_tab.rowconfigure(0, weight=1)
        keyframe_tab.columnconfigure(0, weight=1)
        keyframe_tab.rowconfigure(0, weight=1)
        mask_tab.columnconfigure(0, weight=1)
        mask_tab.rowconfigure(0, weight=1)

        nav_tabs.add(create_tab, text=self._t("tab_create"))
        nav_tabs.add(sync_tab, text=self._t("tab_sync"))
        nav_tabs.add(export_tab, text=self._t("tab_export"))
        nav_tabs.add(transition_tab, text=self._t("tab_transition"))
        nav_tabs.add(keyframe_tab, text=self._t("tab_keyframe"))
        nav_tabs.add(mask_tab, text=self._t("tab_mask"))

        action_card = ttk.Labelframe(
            sync_tab,
            text="Thao tác đồng bộ",
            padding=14,
            style="ProjectCard.TLabelframe",
        )
        action_card.grid(row=0, column=0, sticky=EW)
        action_card.columnconfigure(1, weight=1)

        ttk.Label(action_card, text="Đồng bộ", style="SectionTitle.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        ttk.Label(
            action_card,
            text="Chọn dự án ở panel bên phải rồi bấm Đồng bộ timeline.",
            style="Subtle.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 12))

        self.sync_button = ttk.Button(
            action_card,
            text=self._t("sync_button"),
            command=self._on_sync_audio,
            width=12,
            style="Accent.TButton",
        )
        self.sync_button.grid(row=2, column=0, sticky="w")

        ttk.Label(
            action_card,
            text=f"Thư mục dự án CapCut: {DEFAULT_CAPCUT_PROJECT_ROOT}",
            style="Subtle.TLabel",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))

        export_card = ttk.Labelframe(
            export_tab,
            text="Xuất bản dự án",
            padding=14,
            style="ProjectCard.TLabelframe",
        )
        export_card.grid(row=0, column=0, sticky=EW)
        export_card.columnconfigure(3, weight=1)

        self.export_publish_button = ttk.Button(
            export_card,
            text=self._t("publish_button"),
            command=self._on_export_selected_projects,
            width=12,
            style="Accent.TButton",
        )
        self.export_publish_button.grid(row=0, column=0, sticky="w")

        self.test_click_button = ttk.Button(
            export_card,
            text=self._t("test_click_button"),
            command=self._on_test_click_first_project,
            width=13,
            style="Secondary.TButton",
        )
        self.test_click_button.grid(row=0, column=1, sticky="w", padx=(8, 0))

        export_calib = ttk.Labelframe(
            export_card,
            text="Calib vùng danh sách dự án (Export)",
            padding=8,
            style="ProjectCard.TLabelframe",
        )
        export_calib.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        for i in range(8):
            export_calib.columnconfigure(i, weight=0)

        ttk.Label(export_calib, text="L", style="Subtle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(export_calib, textvariable=self.export_list_left_var, width=6, style="Search.TEntry").grid(row=0, column=1, sticky="w", padx=(4, 8))
        ttk.Label(export_calib, text="T", style="Subtle.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Entry(export_calib, textvariable=self.export_list_top_var, width=6, style="Search.TEntry").grid(row=0, column=3, sticky="w", padx=(4, 8))
        ttk.Label(export_calib, text="W", style="Subtle.TLabel").grid(row=0, column=4, sticky="w")
        ttk.Entry(export_calib, textvariable=self.export_list_width_var, width=6, style="Search.TEntry").grid(row=0, column=5, sticky="w", padx=(4, 8))
        ttk.Label(export_calib, text="H", style="Subtle.TLabel").grid(row=0, column=6, sticky="w")
        ttk.Entry(export_calib, textvariable=self.export_list_height_var, width=6, style="Search.TEntry").grid(row=0, column=7, sticky="w", padx=(4, 0))

        ttk.Label(export_calib, text="FX", style="Subtle.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(export_calib, textvariable=self.export_grid_first_x_var, width=6, style="Search.TEntry").grid(row=1, column=1, sticky="w", padx=(4, 8), pady=(6, 0))
        ttk.Label(export_calib, text="FY", style="Subtle.TLabel").grid(row=1, column=2, sticky="w", pady=(6, 0))
        ttk.Entry(export_calib, textvariable=self.export_grid_first_y_var, width=6, style="Search.TEntry").grid(row=1, column=3, sticky="w", padx=(4, 8), pady=(6, 0))
        ttk.Label(export_calib, text="GX", style="Subtle.TLabel").grid(row=1, column=4, sticky="w", pady=(6, 0))
        ttk.Entry(export_calib, textvariable=self.export_grid_gap_x_var, width=6, style="Search.TEntry").grid(row=1, column=5, sticky="w", padx=(4, 8), pady=(6, 0))
        ttk.Label(export_calib, text="GY", style="Subtle.TLabel").grid(row=1, column=6, sticky="w", pady=(6, 0))
        ttk.Entry(export_calib, textvariable=self.export_grid_gap_y_var, width=6, style="Search.TEntry").grid(row=1, column=7, sticky="w", padx=(4, 0), pady=(6, 0))

        self.pick_region_button = ttk.Button(
            export_calib,
            text=self._t("pick_region_button"),
            command=self._on_pick_project_list_region,
            width=12,
            style="Secondary.TButton",
        )
        self.pick_region_button.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))


        batch_card = ttk.Labelframe(
            create_tab,
            text="Tạo dự án hàng loạt",
            padding=12,
            style="ProjectCard.TLabelframe",
        )
        batch_card.grid(row=0, column=0, sticky=EW)
        batch_card.columnconfigure(1, weight=1)

        ttk.Label(batch_card, text="Thư mục voice:", style="Subtle.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 6))
        ttk.Entry(batch_card, textvariable=self.batch_voices_root_var, style="Search.TEntry").grid(row=0, column=1, sticky=EW, pady=(0, 6))
        ttk.Button(batch_card, text="Chọn", style="Ghost.TButton", command=self._pick_batch_voices_root, width=8).grid(row=0, column=2, padx=(8, 0), pady=(0, 6))

        ttk.Label(batch_card, text="Thư mục video/image:", style="Subtle.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(batch_card, textvariable=self.batch_media_root_var, style="Search.TEntry").grid(row=1, column=1, sticky=EW)
        ttk.Button(batch_card, text="Chọn", style="Ghost.TButton", command=self._pick_batch_media_root, width=8).grid(row=1, column=2, padx=(8, 0))

        ttk.Label(batch_card, text="Tên project (tuỳ chọn):", style="Subtle.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
        ttk.Entry(batch_card, textvariable=self.batch_project_name_var, style="Search.TEntry").grid(row=2, column=1, sticky=EW, pady=(6, 0))

        vol_row = ttk.Frame(batch_card, style="Panel.TFrame")
        vol_row.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        ttk.Label(vol_row, text="Video (dB):", style="Subtle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(vol_row, textvariable=self.batch_video_volume_db_var, width=8, style="Search.TEntry").grid(row=0, column=1, sticky="w", padx=(6, 12))
        ttk.Label(vol_row, text="Audio (dB):", style="Subtle.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Entry(vol_row, textvariable=self.batch_audio_volume_db_var, width=8, style="Search.TEntry").grid(row=0, column=3, sticky="w", padx=(6, 6))
        ttk.Label(vol_row, text="Mặc định 0.0 dB", style="Subtle.TLabel").grid(row=0, column=4, sticky="w")

        self.batch_button = ttk.Button(
            batch_card,
            text="Tạo batch",
            command=self._on_create_batch_projects,
            style="Secondary.TButton",
            width=12,
        )
        self.batch_button.grid(row=4, column=0, sticky="w", pady=(10, 0))

        ttk.Label(
            batch_card,
            textvariable=self.template_info_var,
            style="Subtle.TLabel",
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))

        transition_card = ttk.Labelframe(
            transition_tab,
            text="Thêm hiệu ứng chuyển cảnh",
            padding=12,
            style="ProjectCard.TLabelframe",
        )
        transition_card.grid(row=0, column=0, sticky=NSEW)
        transition_card.columnconfigure(0, weight=1)
        transition_card.columnconfigure(1, weight=1)
        transition_card.columnconfigure(2, weight=1)
        transition_card.rowconfigure(3, weight=1)

        ttk.Label(
            transition_card,
            text="Chọn dự án ở panel bên phải, chọn hiệu ứng rồi bấm Áp dụng chuyển cảnh.",
            style="Subtle.TLabel",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        self.apply_transition_button = ttk.Button(
            transition_card,
            text="Áp dụng",
            style="Accent.TButton",
            command=self._on_apply_transitions_only,
            width=12,
        )
        self.apply_transition_button.grid(row=1, column=0, sticky="w")

        ttk.Label(
            transition_card,
            text="Danh sách hiệu ứng (chọn một hoặc nhiều)",
            style="Subtle.TLabel",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 4))

        checks_host = ttk.Frame(transition_card, style="Panel.TFrame")
        checks_host.grid(row=3, column=0, columnspan=3, sticky=NSEW)
        checks_host.columnconfigure(0, weight=1)
        checks_host.rowconfigure(0, weight=1)
        checks_host.configure(height=200)
        checks_host.grid_propagate(False)

        checks_canvas = tk.Canvas(
            checks_host,
            background=PANEL_2,
            highlightthickness=0,
            bd=0,
            height=200,
        )
        checks_canvas.grid(row=0, column=0, sticky=NSEW)
        self.transition_checks_canvas = checks_canvas

        checks_scroll = tk.Scrollbar(
            checks_host,
            orient="vertical",
            command=checks_canvas.yview,
            width=14,
            relief="raised",
        )
        checks_scroll.grid(row=0, column=1, sticky="ns")
        self.transition_checks_scroll = checks_scroll

        checks_canvas.configure(yscrollcommand=checks_scroll.set)

        self.transition_checks_container = ttk.Frame(checks_canvas, style="Panel.TFrame")
        checks_window = checks_canvas.create_window((0, 0), window=self.transition_checks_container, anchor="nw")

        def _sync_checks_scroll(_event=None) -> None:
            checks_canvas.configure(scrollregion=checks_canvas.bbox("all"))

        def _sync_checks_width(_event=None) -> None:
            checks_canvas.itemconfigure(checks_window, width=checks_canvas.winfo_width())

        def _on_mousewheel(event) -> str:
            if event.delta == 0:
                return "break"
            delta = int(-1 * (event.delta / 120))
            if delta == 0:
                delta = -1 if event.delta > 0 else 1
            checks_canvas.yview_scroll(delta, "units")
            return "break"

        self.transition_checks_container.bind("<Configure>", _sync_checks_scroll)
        checks_canvas.bind("<Configure>", _sync_checks_width)
        checks_canvas.bind("<Enter>", lambda _e: checks_canvas.bind_all("<MouseWheel>", _on_mousewheel))
        checks_canvas.bind("<Leave>", lambda _e: checks_canvas.unbind_all("<MouseWheel>"))

        # Init at top.
        checks_canvas.yview_moveto(0.0)

        keyframe_card = ttk.Labelframe(
            keyframe_tab,
            text="Keyframe Zoom",
            padding=8,
            style="ProjectCard.TLabelframe",
        )
        keyframe_card.grid(row=0, column=0, sticky=NSEW)
        keyframe_card.columnconfigure(0, weight=1)

        row_mode = ttk.Frame(keyframe_card, style="Panel.TFrame")
        row_mode.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(row_mode, text="Kiểu:", style="Subtle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(row_mode, text="In", value="zoom_in", variable=self.keyframe_mode_var).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Radiobutton(row_mode, text="Out", value="zoom_out", variable=self.keyframe_mode_var).grid(row=0, column=2, sticky="w", padx=(8, 0))

        row_values = ttk.Frame(keyframe_card, style="Panel.TFrame")
        row_values.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(row_values, text="Start", style="Subtle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(row_values, textvariable=self.keyframe_start_percent_var, width=6, style="Search.TEntry").grid(row=0, column=1, sticky="w", padx=(4, 10))
        ttk.Label(row_values, text="End", style="Subtle.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Entry(row_values, textvariable=self.keyframe_end_percent_var, width=6, style="Search.TEntry").grid(row=0, column=3, sticky="w", padx=(4, 10))
        ttk.Label(row_values, text="Dur(s)", style="Subtle.TLabel").grid(row=0, column=4, sticky="w")
        ttk.Entry(row_values, textvariable=self.keyframe_duration_seconds_var, width=6, style="Search.TEntry").grid(row=0, column=5, sticky="w", padx=(4, 0))

        row_opts = ttk.Frame(keyframe_card, style="Panel.TFrame")
        row_opts.grid(row=2, column=0, sticky="ew", pady=(0, 4))
        ttk.Checkbutton(
            row_opts,
            text="Only picture",
            variable=self.keyframe_only_picture_var,
            style="Project.TCheckbutton",
        ).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            row_opts,
            text="Full duration",
            variable=self.keyframe_full_duration_var,
            style="Project.TCheckbutton",
        ).grid(row=0, column=1, sticky="w", padx=(12, 0))

        self.apply_keyframe_button = ttk.Button(
            keyframe_card,
            text="Áp dụng",
            style="Accent.TButton",
            command=self._on_apply_keyframes_only,
            width=11,
        )
        self.apply_keyframe_button.grid(row=3, column=0, sticky="w", pady=(2, 0))

        mask_card = ttk.Labelframe(
            mask_tab,
            text="Video Mask",
            padding=8,
            style="ProjectCard.TLabelframe",
        )
        mask_card.grid(row=0, column=0, sticky=NSEW)
        mask_card.columnconfigure(1, weight=1)
        mask_card.rowconfigure(6, weight=1)

        mode_row = ttk.Frame(mask_card, style="Panel.TFrame")
        mode_row.grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(mode_row, text="Mode:", style="Subtle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(mode_row, text="Thông số", variable=self.mask_mode_var, value="params", command=self._on_mask_mode_changed).grid(row=0, column=1, sticky="w", padx=(8, 8))
        ttk.Radiobutton(mode_row, text="Tỉ lệ", variable=self.mask_mode_var, value="ratio", command=self._on_mask_mode_changed).grid(row=0, column=2, sticky="w")

        self.mask_inputs_params_frame = ttk.Frame(mask_card, style="Panel.TFrame")
        self.mask_inputs_params_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self.mask_inputs_params_frame.columnconfigure(1, weight=1)
        ttk.Label(self.mask_inputs_params_frame, text="Overlay W:", style="Subtle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.mask_inputs_params_frame, textvariable=self.mask_overlay_width_var, style="Search.TEntry", width=9).grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Label(self.mask_inputs_params_frame, text="Overlay H:", style="Subtle.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(self.mask_inputs_params_frame, textvariable=self.mask_overlay_height_var, style="Search.TEntry", width=9).grid(row=1, column=1, sticky="w", padx=(6, 0), pady=(4, 0))
        ttk.Label(self.mask_inputs_params_frame, text="Bo góc mask (0..100):", style="Subtle.TLabel").grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(self.mask_inputs_params_frame, textvariable=self.mask_round_corner_var, style="Search.TEntry", width=9).grid(row=2, column=1, sticky="w", padx=(6, 0), pady=(4, 0))

        self.mask_inputs_ratio_frame = ttk.Frame(mask_card, style="Panel.TFrame")
        self.mask_inputs_ratio_frame.columnconfigure(1, weight=1)
        ttk.Label(self.mask_inputs_ratio_frame, text="Tỉ lệ mask/background (%):", style="Subtle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.mask_inputs_ratio_frame, textvariable=self.mask_scale_percent_var, style="Search.TEntry", width=9).grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Label(self.mask_inputs_ratio_frame, text="Bo góc mask (0..100):", style="Subtle.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(self.mask_inputs_ratio_frame, textvariable=self.mask_round_corner_var, style="Search.TEntry", width=9).grid(row=1, column=1, sticky="w", padx=(6, 0), pady=(4, 0))

        action_row = ttk.Frame(mask_card, style="Panel.TFrame")
        action_row.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

        self.apply_mask_button = ttk.Button(
            action_row,
            text="Áp dụng",
            style="Accent.TButton",
            command=self._on_apply_mask_only,
            width=12,
        )
        self.apply_mask_button.grid(row=0, column=0, sticky="w")

        ttk.Label(mask_card, text="Background có sẵn (embedded trong EXE):", style="Subtle.TLabel").grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 4))

        mask_lib_host = ttk.Frame(mask_card, style="Panel.TFrame")
        mask_lib_host.grid(row=6, column=0, columnspan=3, sticky=NSEW)
        mask_lib_host.columnconfigure(0, weight=1)
        mask_lib_host.rowconfigure(0, weight=1)
        mask_lib_host.configure(height=130)
        mask_lib_host.grid_propagate(False)

        mask_lib_canvas = tk.Canvas(mask_lib_host, background=PANEL_2, highlightthickness=0, bd=0, height=130)
        mask_lib_canvas.grid(row=0, column=0, sticky=NSEW)
        mask_lib_scroll = tk.Scrollbar(mask_lib_host, orient="vertical", command=mask_lib_canvas.yview, width=14, relief="raised")
        mask_lib_scroll.grid(row=0, column=1, sticky="ns")
        mask_lib_canvas.configure(yscrollcommand=mask_lib_scroll.set)

        self.mask_library_container = ttk.Frame(mask_lib_canvas, style="Panel.TFrame")
        mask_lib_window = mask_lib_canvas.create_window((0, 0), window=self.mask_library_container, anchor="nw")

        def _sync_masklib_scroll(_event=None) -> None:
            mask_lib_canvas.configure(scrollregion=mask_lib_canvas.bbox("all"))

        def _sync_masklib_width(_event=None) -> None:
            mask_lib_canvas.itemconfigure(mask_lib_window, width=mask_lib_canvas.winfo_width())

        def _on_masklib_mousewheel(event) -> str:
            if event.delta == 0:
                return "break"
            delta = int(-1 * (event.delta / 120))
            if delta == 0:
                delta = -1 if event.delta > 0 else 1
            mask_lib_canvas.yview_scroll(delta, "units")
            return "break"

        self.mask_library_container.bind("<Configure>", _sync_masklib_scroll)
        mask_lib_canvas.bind("<Configure>", _sync_masklib_width)
        mask_lib_canvas.bind("<Enter>", lambda _e: mask_lib_canvas.bind_all("<MouseWheel>", _on_masklib_mousewheel))
        mask_lib_canvas.bind("<Leave>", lambda _e: mask_lib_canvas.unbind_all("<MouseWheel>"))

        right_panel = ttk.Frame(main_frame, style="Panel.TFrame")
        right_panel.grid(row=1, column=1, sticky=NSEW)
        right_panel.columnconfigure(0, weight=1)
        right_panel.rowconfigure(0, weight=1)

        projects_card = ttk.Labelframe(
            right_panel,
            text=self._t("projects_group"),
            padding=12,
            style="ProjectCard.TLabelframe",
        )
        self.projects_card = projects_card
        projects_card.grid(row=0, column=0, sticky=NSEW)
        projects_card.columnconfigure(0, weight=1)
        projects_card.rowconfigure(1, weight=1)

        projects_header = ttk.Frame(projects_card, style="Panel.TFrame")
        projects_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        projects_header.columnconfigure(0, weight=1)

        ttk.Label(
            projects_header,
            textvariable=self.project_stats_var,
            style="Subtle.TLabel",
        ).grid(row=0, column=0, sticky="w")

        self.refresh_button = ttk.Button(
            projects_header,
            text=self._t("refresh_button"),
            command=self.refresh_projects,
            width=12,
            style="Secondary.TButton",
        )
        self.refresh_button.grid(row=0, column=1, sticky="e")


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
        self.projects_scroll = tk.Scrollbar(
            list_host,
            orient="vertical",
            command=self.projects_canvas.yview,
            width=14,
            relief="raised",
        )
        self.projects_scroll.grid(row=0, column=1, sticky="ns")
        self.projects_canvas.configure(yscrollcommand=self.projects_scroll.set)

        self.projects_container = ttk.Frame(self.projects_canvas, style="Panel.TFrame")
        self.projects_canvas_window = self.projects_canvas.create_window(
            (0, 0),
            window=self.projects_container,
            anchor="nw",
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

        log_card = ttk.Labelframe(
            main_frame,
            text=self._t("log_group"),
            padding=12,
            style="ProjectCard.TLabelframe",
        )
        self.log_card = log_card
        log_card.grid(row=3, column=0, columnspan=2, sticky=NSEW, pady=(10, 0))
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(1, weight=1)
        main_frame.rowconfigure(3, weight=0)

        self.log_subtitle_label = ttk.Label(
            log_card,
            text=self._t("log_subtitle"),
            style="Subtle.TLabel",
        )
        self.log_subtitle_label.grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.log_text = ScrolledText(
            log_card,
            height=8,
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

    def _wire_events(self) -> None:
        if self.projects_canvas is not None:
            self.projects_canvas.bind("<Configure>", self._on_projects_canvas_configure)
            self.projects_canvas.bind("<Enter>", lambda _e: self.projects_canvas.bind_all("<MouseWheel>", self._on_projects_mousewheel))
            self.projects_canvas.bind("<Leave>", lambda _e: self.projects_canvas.unbind_all("<MouseWheel>"))
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
        if event.delta == 0:
            return "break"
        delta = int(-1 * (event.delta / 120))
        if delta == 0:
            delta = -1 if event.delta > 0 else 1
        self.projects_canvas.yview_scroll(delta, "units")
        return "break"

    def _toggle_project(self) -> None:
        self._update_project_stats()

    def _update_project_stats(self) -> None:
        total = len(self.project_items)
        selected = sum(1 for _, _, var, _ in self.project_items if var.get())
        self.project_stats_var.set(self._t("projects_selected", selected=selected, total=total))

    def _collect_selected_projects(self) -> list[str]:
        out: list[str] = []
        for path, _, var, _ in self.project_items:
            if var.get():
                out.append(path)
        return sorted(out)

    @staticmethod
    def _safe_ratio(var: tk.StringVar, default: float) -> float:
        try:
            v = float((var.get() or "").strip())
        except Exception:
            return default
        return max(0.0, min(1.0, v))

    def _confirm_bulk_action(self, action_name: str, projects: list[str]) -> bool:
        count = len(projects)
        if count < BULK_ACTION_WARNING_THRESHOLD:
            return True

        preview = "\n".join(f"- {Path(p).name}" for p in projects[:8])
        if count > 8:
            preview += f"\n... và {count - 8} dự án khác"

        return messagebox.askyesno(
            "Xác nhận thao tác hàng loạt",
            (
                f"Bạn sắp {action_name} cho {count} dự án.\n\n"
                f"Danh sách:\n{preview}\n\n"
                "Tiếp tục không?"
            ),
        )

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
        dirs = [p for p in root.iterdir() if p.is_dir()]
        return sorted(
            dirs,
            key=lambda p: (-p.stat().st_mtime, p.name.lower()),
        )

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

    def _extract_index(self, name: str) -> int:
        nums = re.findall(r"\d+", name)
        if not nums:
            return -1
        return int(nums[-1])

    def _scan_files(self, folder: Path, exts: set[str]) -> list[Path]:
        if not folder.exists() or not folder.is_dir():
            return []
        files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts]
        return sorted(files, key=lambda p: (self._extract_index(p.stem), p.name.lower()))

    def _probe_media_duration_us(self, path: Path) -> int:
        ext = path.suffix.lower()
        if ext in VIDEO_EXTS:
            try:
                return sec_to_us(probe_audio_duration_seconds(path))
            except Exception:
                return 5_000_000
        return 5_000_000

    def _clone_with_new_id(self, template_obj: dict) -> dict:
        obj = copy.deepcopy(template_obj) if isinstance(template_obj, dict) else {}
        obj["id"] = str(uuid4()).upper()
        return obj

    def _get_or_create_track(self, draft: dict, track_type: str) -> dict:
        tracks = draft.get("tracks")
        if not isinstance(tracks, list):
            tracks = []
            draft["tracks"] = tracks

        for tr in tracks:
            if str(tr.get("type") or tr.get("track_type") or "").lower() == track_type:
                if not isinstance(tr.get("segments"), list):
                    tr["segments"] = []
                return tr

        tr = {"type": track_type, "segments": []}
        tracks.append(tr)
        return tr

    def _fill_project_draft_with_inputs(
        self,
        draft: dict,
        media_dir: Path,
        voice_dir: Path,
        video_volume: float = 1.0,
        audio_volume: float = 1.0,
    ) -> tuple[int, int]:
        media_files = self._scan_files(media_dir, MEDIA_EXTS)
        voice_files = self._scan_files(voice_dir, AUDIO_EXTS)

        if not media_files:
            raise ValueError(f"Không có file video/ảnh trong: {media_dir}")
        if not voice_files:
            raise ValueError(f"Không có file voice trong: {voice_dir}")

        materials = draft.get("materials")
        if not isinstance(materials, dict):
            materials = {}
            draft["materials"] = materials

        template_video_mat = (materials.get("videos") or [{}])[0] if isinstance(materials.get("videos"), list) else {}
        template_audio_mat = (materials.get("audios") or [{}])[0] if isinstance(materials.get("audios"), list) else {}
        template_canvas_mat = (materials.get("canvases") or [{}])[0] if isinstance(materials.get("canvases"), list) else {}

        video_track = self._get_or_create_track(draft, "video")
        audio_track = self._get_or_create_track(draft, "audio")

        template_video_seg = (video_track.get("segments") or [{}])[0] if isinstance(video_track.get("segments"), list) else {}
        template_audio_seg = (audio_track.get("segments") or [{}])[0] if isinstance(audio_track.get("segments"), list) else {}

        videos: list[dict] = []
        audios: list[dict] = []
        canvases: list[dict] = []

        for mf in media_files:
            mid = str(uuid4()).upper()
            dur = self._probe_media_duration_us(mf)

            vm = self._clone_with_new_id(template_video_mat)
            vm["id"] = mid
            vm["type"] = "video"
            vm["path"] = str(mf).replace("\\", "/")
            vm["material_name"] = mf.name
            vm["duration"] = int(dur)
            videos.append(vm)

            cm = self._clone_with_new_id(template_canvas_mat)
            cm["type"] = cm.get("type") or "canvas_color"
            canvases.append(cm)

        for af in voice_files:
            aid = str(uuid4()).upper()
            dur = sec_to_us(probe_audio_duration_seconds(af))

            am = self._clone_with_new_id(template_audio_mat)
            am["id"] = aid
            am["type"] = am.get("type") or "extract_music"
            am["path"] = str(af).replace("\\", "/")
            am["name"] = af.name
            am["duration"] = int(dur)
            audios.append(am)

        materials["videos"] = videos
        materials["audios"] = audios
        materials["canvases"] = canvases

        v_segments: list[dict] = []
        v_cursor = 0
        for idx, vm in enumerate(videos):
            dur = int(vm.get("duration") or 5_000_000)
            seg = self._clone_with_new_id(template_video_seg)
            seg["material_id"] = vm["id"]
            seg["target_timerange"] = {"start": v_cursor, "duration": dur}
            seg["source_timerange"] = {"start": 0, "duration": dur}
            seg["render_index"] = idx
            seg["track_render_index"] = 0
            seg["volume"] = float(video_volume)
            seg["last_nonzero_volume"] = float(video_volume)
            v_segments.append(seg)
            v_cursor += dur

        a_segments: list[dict] = []
        a_cursor = 0
        for idx, am in enumerate(audios):
            dur = int(am.get("duration") or 0)
            seg = self._clone_with_new_id(template_audio_seg)
            seg["material_id"] = am["id"]
            seg["target_timerange"] = {"start": a_cursor, "duration": dur}
            seg["source_timerange"] = {"start": 0, "duration": dur}
            seg["render_index"] = idx
            seg["track_render_index"] = 1
            seg["volume"] = float(audio_volume)
            seg["last_nonzero_volume"] = float(audio_volume)
            a_segments.append(seg)
            a_cursor += dur

        video_track["segments"] = v_segments
        audio_track["segments"] = a_segments

        total_us = max(v_cursor, a_cursor)
        for k in ["duration", "tm_duration", "max_duration", "draft_duration"]:
            if isinstance(draft.get(k), (int, float)):
                draft[k] = int(total_us)

        return len(videos), len(audios)

    def _hydrate_project_drafts_with_inputs(
        self,
        project_dir: Path,
        media_dir: Path,
        voice_dir: Path,
        video_volume: float = 1.0,
        audio_volume: float = 1.0,
    ) -> tuple[int, int]:
        main_draft = project_dir / "draft_content.json"
        if not main_draft.exists():
            raise FileNotFoundError(f"Thiếu file: {main_draft}")

        draft = json.loads(main_draft.read_text(encoding="utf-8"))
        media_count, voice_count = self._fill_project_draft_with_inputs(
            draft,
            media_dir,
            voice_dir,
            video_volume=video_volume,
            audio_volume=audio_volume,
        )
        main_draft.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")

        timelines_dir = project_dir / "Timelines"
        if timelines_dir.exists() and timelines_dir.is_dir():
            for child in timelines_dir.iterdir():
                p = child / "draft_content.json"
                if not child.is_dir() or not p.exists():
                    continue
                d = json.loads(p.read_text(encoding="utf-8"))
                self._fill_project_draft_with_inputs(
                    d,
                    media_dir,
                    voice_dir,
                    video_volume=video_volume,
                    audio_volume=audio_volume,
                )
                p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

        meta_path = project_dir / "draft_meta_info.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                total_us = int(max(sum(int(x.get("duration") or 0) for x in draft.get("materials", {}).get("videos", [])), sum(int(x.get("duration") or 0) for x in draft.get("materials", {}).get("audios", []))))
                for k in ["tm_duration", "duration", "max_duration"]:
                    if isinstance(meta.get(k), (int, float)):
                        meta[k] = total_us
                meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

        return media_count, voice_count

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

    def _build_batch_jobs(self, voices_root: Path, media_root: Path, project_name: str) -> list[tuple[str, Path, Path]]:
        voice_children = self._list_child_dirs(voices_root)
        media_children = self._list_child_dirs(media_root)

        has_subfolders = bool(voice_children or media_children)
        if not has_subfolders:
            base = project_name.strip() or voices_root.name or "project_moi"
            return [(base, voices_root, media_root)]

        media_map = {p.name.lower(): p for p in media_children}
        jobs: list[tuple[str, Path, Path]] = []
        for v in voice_children:
            m = media_map.get(v.name.lower())
            if m is None:
                self.log_queue.put(f"[BATCH] Bỏ qua '{v.name}' vì không có thư mục media trùng tên.\n")
                continue
            if project_name.strip():
                jobs.append((f"{project_name.strip()}_{v.name}", v, m))
            else:
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
        project_name = self.batch_project_name_var.get().strip()

        try:
            video_volume_db = float(self.batch_video_volume_db_var.get().strip())
            audio_volume_db = float(self.batch_audio_volume_db_var.get().strip())
        except ValueError:
            messagebox.showerror("Input không hợp lệ", "Âm lượng video/audio phải là số dB (ví dụ: 0, -3, 2.5).")
            return

        video_volume = math.pow(10.0, video_volume_db / 20.0)
        audio_volume = math.pow(10.0, audio_volume_db / 20.0)

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
            f"template={template_project}\nvoices_root={voices_root}\nmedia_root={media_root}\nproject_name={project_name or '[auto]'}\n"
            f"video_volume_db={video_volume_db} -> linear={video_volume}\n"
            f"audio_volume_db={audio_volume_db} -> linear={audio_volume}\n"
        )
        self._set_status("Đang tạo project hàng loạt từ template...", "info")
        self._set_running_state(True)
        self.current_task_running = True

        threading.Thread(
            target=self._execute_batch_create,
            args=(
                template_project,
                voices_root,
                media_root,
                project_name,
                video_volume,
                audio_volume,
            ),
            daemon=True,
        ).start()

    def _execute_batch_create(
        self,
        template_project: Path,
        voices_root: Path,
        media_root: Path,
        project_name: str,
        video_volume: float,
        audio_volume: float,
    ) -> None:
        output_buf = io.StringIO()
        overall_code = 0
        try:
            jobs = self._build_batch_jobs(voices_root, media_root, project_name)
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

                    media_count, voice_count = self._hydrate_project_drafts_with_inputs(
                        new_project,
                        m_dir,
                        v_dir,
                        video_volume=video_volume,
                        audio_volume=audio_volume,
                    )

                    print(f"images={images_dir}")
                    print(f"voices={voices_dir}")
                    print(f"project_materials: videos={media_count} audios={voice_count}")
                    print("sync_step=skipped (create-only semantics)")
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

    def _load_transition_catalog_to_input(self, show_message: bool = True) -> None:
        selected_projects = self._collect_selected_projects()
        sample_draft = None
        if selected_projects:
            try:
                p = Path(selected_projects[0]) / "draft_content.json"
                if p.exists():
                    sample_draft = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                sample_draft = None

        catalog = load_transition_catalog(sample_project_draft=sample_draft)
        if not catalog:
            if show_message:
                messagebox.showwarning("Transition catalog", "Không tìm thấy effect transition trong project thư viện.")
            return

        def _is_vietnamese_friendly_name(name: str) -> bool:
            n = (name or "").strip()
            if not n:
                return False

            low = n.lower()
            if low.isdigit():
                return False
            if re.fullmatch(r"\d{12,}", low):
                return False
            if re.fullmatch(r"[a-z0-9_\-]{18,}", low):
                return False
            if "editor_" in low or "_config" in low or "tag_" in low:
                return False
            if low.startswith("amazing"):
                return False

            # Accept human-readable names (Vietnamese with/without dấu), reject technical tokens.
            if len(n) < 2:
                return False
            if not re.search(r"[A-Za-zÀ-ỹĐđ]", n):
                return False
            return True

        curated: list[dict] = []
        fallback_readable: list[dict] = []
        for item in catalog:
            effect_id = str(item.get("effect_id") or "").strip()
            name = str(item.get("name") or "").strip()
            if not effect_id:
                continue

            # strict curated path (prefer Vietnamese-friendly names)
            if _is_vietnamese_friendly_name(name) and name != effect_id:
                curated.append(item)
                continue

            # fallback path: still show readable non-empty names, avoid raw id-only entries
            if name and name != effect_id and not re.fullmatch(r"\d{10,}", name):
                fallback_readable.append(item)

        source_for_ui = curated if curated else fallback_readable

        seen_ids: set[str] = set()
        filtered_catalog: list[dict] = []
        for item in source_for_ui:
            eid = str(item.get("effect_id") or "").strip()
            if not eid or eid in seen_ids:
                continue
            seen_ids.add(eid)
            filtered_catalog.append(item)
            if len(filtered_catalog) >= TRANSITION_CATALOG_LIMIT:
                break

        if not filtered_catalog:
            if show_message:
                messagebox.showwarning(
                    "Transition catalog",
                    "Không tìm thấy effect transition có tên dễ đọc trong project thư viện.",
                )
            return

        self.transition_catalog = filtered_catalog
        self.transition_effects_var.set("")

        if self.transition_checks_container is not None:
            for child in self.transition_checks_container.winfo_children():
                child.destroy()
        if self.transition_checks_canvas is not None:
            self.transition_checks_canvas.yview_moveto(0.0)

        self.transition_check_vars = []
        effect_ids = []

        for idx, item in enumerate(filtered_catalog):
            effect_id = str(item.get("effect_id") or "").strip()
            if not effect_id:
                continue
            effect_ids.append(effect_id)

            name = str(item.get("name") or effect_id)
            cat = str(item.get("category_name") or "")
            if (not cat) or name == effect_id:
                if effect_id == "6864867302936941064":
                    name = "Chớp mắt"
                    cat = cat or "Đang thịnh hành"
                elif effect_id == "7606637909403290887":
                    name = "Cảnh mở ra"
                    cat = cat or "Đang thịnh hành"

            label = name if not cat else f"{name} ({cat})"
            if self.transition_checks_container is not None:
                v = tk.BooleanVar(value=False)
                cb = ttk.Checkbutton(
                    self.transition_checks_container,
                    text=label,
                    variable=v,
                    style="Transition.TCheckbutton",
                )
                idx_cb = len(self.transition_check_vars)
                row = idx_cb // 2
                col = idx_cb % 2
                cb.grid(row=row, column=col, sticky="w", padx=(0, 18), pady=(0, 0))
                self.transition_check_vars.append(v)

        def _refresh_transition_scrollbar() -> None:
            if self.transition_checks_canvas is None or self.transition_checks_container is None:
                return
            self.transition_checks_container.columnconfigure(0, weight=1)
            self.transition_checks_container.columnconfigure(1, weight=1)
            bbox = self.transition_checks_canvas.bbox("all")
            if bbox is None:
                self.transition_checks_canvas.configure(scrollregion=(0, 0, 0, 0))
                return
            self.transition_checks_canvas.configure(scrollregion=bbox)

        self.root.after_idle(_refresh_transition_scrollbar)
        self._append_log(f"[TRANSITION] catalog_loaded={len(effect_ids)} (limit={TRANSITION_CATALOG_LIMIT}, vietnamese_name_only_strict)\n")
        self._set_status(f"Đã tự nạp {len(effect_ids)} transition effects tiếng Việt (tối đa {TRANSITION_CATALOG_LIMIT})", "success")

    def _get_selected_transition_effect_ids(self) -> list[str]:
        out: list[str] = []
        for idx, item in enumerate(self.transition_catalog):
            if idx >= len(self.transition_check_vars):
                continue
            if not self.transition_check_vars[idx].get():
                continue
            effect_id = str(item.get("effect_id") or "").strip()
            if effect_id:
                out.append(effect_id)
        return out

    def _on_load_transition_pack_zip(self) -> None:
        zip_path = filedialog.askopenfilename(
            title="Chọn Transition Pack ZIP",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
        )
        if not zip_path:
            return

        try:
            copied = seed_effect_cache_from_zip(Path(zip_path))
            self._append_log(f"[TRANSITION] loaded_zip={zip_path} copied_effects={copied}\n")
            if copied <= 0:
                messagebox.showwarning(
                    "Transition Pack",
                    "Không import được effect nào từ file ZIP (có thể đã tồn tại hoặc sai định dạng).",
                )
            else:
                messagebox.showinfo(
                    "Transition Pack",
                    f"Đã import {copied} effect từ ZIP vào cache CapCut.",
                )
            self._load_transition_catalog_to_input(show_message=False)
        except Exception as exc:
            messagebox.showerror("Transition Pack", f"Load ZIP thất bại: {exc}")

    def _on_apply_transitions_only(self) -> None:
        if self.current_process is not None or self.current_task_running:
            messagebox.showwarning("Đang bận", "Đang có tiến trình chạy. Vui lòng chờ xong.")
            return

        selected_projects = self._collect_selected_projects()
        if not selected_projects:
            messagebox.showerror("Chưa chọn dự án", "Vui lòng chọn ít nhất 1 dự án trong danh sách.")
            return
        if not self._confirm_bulk_action("thêm transition", selected_projects):
            return

        selected_effect_ids = self._get_selected_transition_effect_ids()
        if not selected_effect_ids:
            messagebox.showerror("Thiếu hiệu ứng", "Hãy chọn ít nhất 1 hiệu ứng trong danh sách.")
            return

        self.current_action = "transition_apply"
        self._append_log("\n--- Apply transitions only ---\n")
        self._append_log(
            f"projects={len(selected_projects)} selected_effects={len(selected_effect_ids)}\n"
        )
        self._set_status(f"Đang thêm transition cho {len(selected_projects)} dự án...", "info")
        self._set_running_state(True)
        self.current_task_running = True

        threading.Thread(
            target=self._execute_apply_transitions_only,
            args=(selected_projects, selected_effect_ids),
            daemon=True,
        ).start()

    def _execute_apply_transitions_only(
        self,
        projects: list[str],
        selected_effect_ids: list[str],
    ) -> None:
        output_buf = io.StringIO()
        overall_code = 0
        try:
            with contextlib.redirect_stdout(output_buf):
                for idx, project in enumerate(projects, start=1):
                    project_dir = Path(project)
                    print(f"--- transition project {idx}/{len(projects)}: {project_dir} ---")

                    bundle = load_project(project_dir)
                    catalog = load_transition_catalog(sample_project_draft=bundle.main_draft)
                    added_main = apply_random_transitions_to_draft(
                        bundle.main_draft,
                        catalog,
                        selected_effect_ids=selected_effect_ids,
                    )
                    write_json_atomic(bundle.main_draft_path, bundle.main_draft)
                    print(f"main_transitions_added={added_main}")

                    for tp in bundle.timeline_draft_paths:
                        d = bundle.timelines[tp]
                        added_tl = apply_random_transitions_to_draft(
                            d,
                            catalog,
                            selected_effect_ids=selected_effect_ids,
                        )
                        write_json_atomic(tp, d)
                        print(f"timeline={tp} transitions_added={added_tl}")
        except Exception:
            output_buf.write(traceback.format_exc())
            overall_code = 1

        out = output_buf.getvalue()
        if out:
            self.log_queue.put(out)
        self.log_queue.put(f"PROCESS_EXIT:{overall_code}")

    def _parse_background_paths(self, raw_text: str) -> list[str]:
        txt = (raw_text or "").strip()
        if not txt:
            return []
        chunks = re.split(r"[,;\n]+", txt)
        out: list[str] = []
        seen: set[str] = set()
        for c in chunks:
            item = c.strip().strip('"').strip("'")
            if not item:
                continue
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    def _on_toggle_mask_item(self) -> None:
        if not self.mask_library_check_vars:
            self.mask_check_all_var.set(False)
            return
        all_checked = all(v.get() for v in self.mask_library_check_vars)
        self.mask_check_all_var.set(all_checked)

    def _on_toggle_mask_check_all(self) -> None:
        val = bool(self.mask_check_all_var.get())
        for v in self.mask_library_check_vars:
            v.set(val)

    def _load_mask_library_to_input(self, show_message: bool = True) -> None:
        self.mask_library_catalog = []
        self.mask_library_check_vars = []
        self.mask_check_all_var.set(False)
        if self.mask_library_container is not None:
            for child in self.mask_library_container.winfo_children():
                child.destroy()

        candidates = load_mask_background_library()
        if not candidates:
            if show_message:
                messagebox.showwarning(
                    "Mask library",
                    "Không có background pack trong tool. Hãy build kèm mask_background_pack.",
                )
            return

        self.mask_library_catalog = candidates

        if self.mask_library_container is not None:
            ttk.Checkbutton(
                self.mask_library_container,
                text="Check all",
                variable=self.mask_check_all_var,
                command=self._on_toggle_mask_check_all,
                style="Transition.TCheckbutton",
            ).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 4))

            for idx, item in enumerate(candidates, start=1):
                v = tk.BooleanVar(value=False)
                src = str(item.get("source") or "")
                prefix = f"[{src}] " if src else ""
                display_name = str(item.get("display_name") or item.get("name") or "")
                raw_name = str(item.get("name") or "")
                if display_name and display_name != raw_name:
                    label = f"{prefix}{display_name} ({raw_name})"
                else:
                    label = f"{prefix}{raw_name}"
                short_label = label if len(label) <= 72 else (label[:69] + "...")
                cb = ttk.Checkbutton(
                    self.mask_library_container,
                    text=short_label,
                    variable=v,
                    command=self._on_toggle_mask_item,
                    style="Transition.TCheckbutton",
                )
                cb.grid(row=idx, column=0, sticky="ew", padx=(12, 8), pady=(0, 2))
                self.mask_library_check_vars.append(v)

        self._append_log(f"[MASK] library_loaded={len(candidates)} (favorite/name mode)\n")

    def _on_refresh_mask_library(self) -> None:
        self._load_mask_library_to_input(show_message=True)

    def _on_mask_mode_changed(self) -> None:
        mode = str(self.mask_mode_var.get() or "params").strip().lower()
        if self.mask_inputs_params_frame is None or self.mask_inputs_ratio_frame is None:
            return
        if mode == "ratio":
            self.mask_inputs_params_frame.grid_remove()
            self.mask_inputs_ratio_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        else:
            self.mask_inputs_ratio_frame.grid_remove()
            self.mask_inputs_params_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 0))

    def _get_selected_mask_library_paths(self) -> list[str]:
        out: list[str] = []
        for idx, item in enumerate(self.mask_library_catalog):
            if idx >= len(self.mask_library_check_vars):
                continue
            if not self.mask_library_check_vars[idx].get():
                continue
            p = str(item.get("path") or "").strip()
            if p:
                out.append(p)
        return out

    def _validate_mask_inputs(self) -> tuple[float, float, float, float, list[str]] | None:
        mode = str(self.mask_mode_var.get() or "params").strip().lower()

        try:
            rc = float(self.mask_round_corner_var.get().strip())
        except ValueError:
            messagebox.showerror("Thiếu input", "Bo góc mask phải là số hợp lệ.")
            return None

        if rc < 0 or rc > 100:
            messagebox.showerror("Input không hợp lệ", "Bo góc mask phải nằm trong 0..100.")
            return None

        if mode == "ratio":
            try:
                scale_pct = float(self.mask_scale_percent_var.get().strip())
            except ValueError:
                messagebox.showerror("Thiếu input", "Tỉ lệ mask/background phải là số hợp lệ.")
                return None
            if scale_pct < 1 or scale_pct > 300:
                messagebox.showerror("Input không hợp lệ", "Tỉ lệ mask/background phải nằm trong 1..300 (%).")
                return None
            # Mode tỉ lệ: ẩn W/H và dùng baseline mặc định.
            w, h = 1800.0, 928.0
        else:
            try:
                w = float(self.mask_overlay_width_var.get().strip())
                h = float(self.mask_overlay_height_var.get().strip())
            except ValueError:
                messagebox.showerror("Thiếu input", "Overlay W/H phải là số hợp lệ.")
                return None
            if w <= 0 or h <= 0:
                messagebox.showerror("Input không hợp lệ", "Overlay W/H phải > 0.")
                return None
            if w > 8000 or h > 8000:
                messagebox.showerror("Input không hợp lệ", "Overlay W/H quá lớn (<= 8000).")
                return None
            # Mode thông số: ưu tiên W/H trực tiếp nên scale mặc định 100%.
            scale_pct = 100.0

        selected_library_paths = self._get_selected_mask_library_paths()
        if not selected_library_paths:
            messagebox.showerror("Thiếu background", "Chưa chọn background mask nào.")
            return None

        bg_paths: list[str] = []
        seen: set[str] = set()
        for p in selected_library_paths:
            key = p.lower()
            if key in seen:
                continue
            seen.add(key)
            bg_paths.append(p)

        for p in bg_paths:
            if not Path(p).exists():
                messagebox.showerror("Background không tồn tại", f"Không tìm thấy file: {p}")
                return None

        return w, h, rc, scale_pct, bg_paths

    def _on_apply_mask_only(self) -> None:
        if self.current_process is not None or self.current_task_running:
            messagebox.showwarning("Đang bận", "Đang có tiến trình chạy. Vui lòng chờ xong.")
            return

        selected_projects = self._collect_selected_projects()
        if not selected_projects:
            messagebox.showerror("Chưa chọn dự án", "Vui lòng chọn ít nhất 1 dự án trong danh sách.")
            return
        if not self._confirm_bulk_action("áp dụng mask", selected_projects):
            return

        validated = self._validate_mask_inputs()
        if validated is None:
            return
        overlay_w, overlay_h, round_corner, scale_pct, bg_paths = validated

        self.current_action = "mask_apply"
        self._append_log("\n--- Apply mask ---\n")
        self._append_log(
            f"projects={len(selected_projects)} overlay={overlay_w}x{overlay_h} round_corner={round_corner} scale_pct={scale_pct} backgrounds={len(bg_paths)} catalog={MASK_BACKGROUND_CATALOG_PATH}\n"
        )
        self._set_status(f"Đang áp dụng mask cho {len(selected_projects)} dự án...", "info")
        self._set_running_state(True)
        self.current_task_running = True

        threading.Thread(
            target=self._execute_apply_mask_only,
            args=(selected_projects, overlay_w, overlay_h, round_corner, scale_pct, bg_paths),
            daemon=True,
        ).start()

    def _execute_apply_mask_only(
        self,
        projects: list[str],
        overlay_w: float,
        overlay_h: float,
        round_corner: float,
        scale_pct: float,
        bg_paths: list[str],
    ) -> None:
        output_buf = io.StringIO()
        overall_code = 0

        mask_template_draft: dict | None = None
        try:
            template_path = DEFAULT_CAPCUT_PROJECT_ROOT / MASK_TEMPLATE_PROJECT_NAME / "draft_content.json"
            if template_path.exists():
                mask_template_draft = json.loads(template_path.read_text(encoding="utf-8"))
        except Exception:
            mask_template_draft = None

        try:
            with contextlib.redirect_stdout(output_buf):
                print(f"mask_template={'external' if mask_template_draft else 'project_fallback'}")
                for idx, project in enumerate(projects, start=1):
                    project_dir = Path(project)
                    print(f"--- mask project {idx}/{len(projects)}: {project_dir} ---")
                    print(f"overlay_size={overlay_w}x{overlay_h}")
                    print(f"background_inputs={len(bg_paths)}")

                    bundle = load_project(project_dir)
                    template_for_apply = mask_template_draft if isinstance(mask_template_draft, dict) else bundle.main_draft

                    result_main = apply_mask_to_draft(
                        bundle.main_draft,
                        overlay_width=overlay_w,
                        overlay_height=overlay_h,
                        round_corner=round_corner,
                        mask_scale_percent=scale_pct,
                        mask_mode=str(self.mask_mode_var.get() or "params"),
                        background_paths=bg_paths,
                        template_draft=template_for_apply,
                        background_catalog_path=MASK_BACKGROUND_CATALOG_PATH,
                    )
                    write_json_atomic(bundle.main_draft_path, bundle.main_draft)
                    print(f"main_mask_updated={result_main.get('updated', 0)} bg_catalog_added={result_main.get('bg_added', 0)}")

                    for tp in bundle.timeline_draft_paths:
                        d = bundle.timelines[tp]
                        result_tl = apply_mask_to_draft(
                            d,
                            overlay_width=overlay_w,
                            overlay_height=overlay_h,
                            round_corner=round_corner,
                            mask_scale_percent=scale_pct,
                            mask_mode=str(self.mask_mode_var.get() or "params"),
                            background_paths=bg_paths,
                            template_draft=template_for_apply,
                            background_catalog_path=MASK_BACKGROUND_CATALOG_PATH,
                        )
                        write_json_atomic(tp, d)
                        print(
                            f"timeline={tp} mask_updated={result_tl.get('updated', 0)} bg_catalog_added={result_tl.get('bg_added', 0)}"
                        )
        except Exception:
            output_buf.write(traceback.format_exc())
            overall_code = 1

        out = output_buf.getvalue()
        if out:
            self.log_queue.put(out)
        self.log_queue.put(f"PROCESS_EXIT:{overall_code}")

    def _on_keyframe_mode_changed(self) -> None:
        mode = self.keyframe_mode_var.get()
        try:
            s = float(self.keyframe_start_percent_var.get().strip())
            e = float(self.keyframe_end_percent_var.get().strip())
        except Exception:
            return

        # Keep UX intuitive: zoom in => start <= end, zoom out => start >= end.
        if mode == "zoom_in" and s > e:
            self.keyframe_start_percent_var.set(f"{e:g}")
            self.keyframe_end_percent_var.set(f"{s:g}")
        elif mode == "zoom_out" and s < e:
            self.keyframe_start_percent_var.set(f"{e:g}")
            self.keyframe_end_percent_var.set(f"{s:g}")

    def _validate_keyframe_inputs(self) -> tuple[float, float, bool, float] | None:
        mode = self.keyframe_mode_var.get()
        if mode not in {"zoom_in", "zoom_out"}:
            messagebox.showerror("Thiếu input", "Loại zoom không hợp lệ.")
            return None

        try:
            start_percent = float(self.keyframe_start_percent_var.get().strip())
            end_percent = float(self.keyframe_end_percent_var.get().strip())
        except ValueError:
            messagebox.showerror("Thiếu input", "Start/End (%) phải là số hợp lệ.")
            return None

        if start_percent <= 0 or end_percent <= 0:
            messagebox.showerror("Input không hợp lệ", "Start/End (%) phải > 0.")
            return None

        # Keep numeric range safe enough for customer use.
        if start_percent < 10 or start_percent > 1000 or end_percent < 10 or end_percent > 1000:
            messagebox.showerror("Input không hợp lệ", "Start/End (%) phải nằm trong khoảng 10..1000.")
            return None

        if abs(start_percent - end_percent) < 1e-9:
            messagebox.showerror("Input không hợp lệ", "Start và End không được bằng nhau (không tạo chuyển động zoom).")
            return None

        if mode == "zoom_in" and not (start_percent < end_percent):
            messagebox.showerror("Input không hợp lệ", "Với Zoom in: Start (%) phải nhỏ hơn End (%).")
            return None

        if mode == "zoom_out" and not (start_percent > end_percent):
            messagebox.showerror("Input không hợp lệ", "Với Zoom out: Start (%) phải lớn hơn End (%).")
            return None

        use_full_duration = bool(self.keyframe_full_duration_var.get())
        duration_seconds = 0.0
        if not use_full_duration:
            try:
                duration_seconds = float(self.keyframe_duration_seconds_var.get().strip())
            except ValueError:
                messagebox.showerror("Thiếu input", "Duration (giây) phải là số hợp lệ.")
                return None
            if duration_seconds <= 0:
                messagebox.showerror("Input không hợp lệ", "Duration (giây) phải > 0.")
                return None
            if duration_seconds > 36000:
                messagebox.showerror("Input không hợp lệ", "Duration (giây) quá lớn (tối đa 36000s).")
                return None

        return start_percent, end_percent, use_full_duration, duration_seconds

    def _on_apply_keyframes_only(self) -> None:
        if self.current_process is not None or self.current_task_running:
            messagebox.showwarning("Đang bận", "Đang có tiến trình chạy. Vui lòng chờ xong.")
            return

        selected_projects = self._collect_selected_projects()
        if not selected_projects:
            messagebox.showerror("Chưa chọn dự án", "Vui lòng chọn ít nhất 1 dự án trong danh sách.")
            return
        if not self._confirm_bulk_action("thêm keyframe", selected_projects):
            return

        validated = self._validate_keyframe_inputs()
        if validated is None:
            return
        start_percent, end_percent, use_full_duration, duration_seconds = validated

        self.current_action = "keyframe_apply"
        self._append_log("\n--- Apply keyframe zoom ---\n")
        self._append_log(
            f"projects={len(selected_projects)} mode={self.keyframe_mode_var.get()} only_picture={self.keyframe_only_picture_var.get()} start={start_percent}% end={end_percent}% full_duration={use_full_duration} duration_s={duration_seconds}\n"
        )
        self._set_status(f"Đang thêm keyframe cho {len(selected_projects)} dự án...", "info")
        self._set_running_state(True)
        self.current_task_running = True

        threading.Thread(
            target=self._execute_apply_keyframes_only,
            args=(
                selected_projects,
                self.keyframe_mode_var.get(),
                bool(self.keyframe_only_picture_var.get()),
                start_percent,
                end_percent,
                use_full_duration,
                duration_seconds,
            ),
            daemon=True,
        ).start()

    def _execute_apply_keyframes_only(
        self,
        projects: list[str],
        zoom_mode: str,
        only_picture: bool,
        start_percent: float,
        end_percent: float,
        use_full_duration: bool,
        duration_seconds: float,
    ) -> None:
        output_buf = io.StringIO()
        overall_code = 0

        try:
            with contextlib.redirect_stdout(output_buf):
                for idx, project in enumerate(projects, start=1):
                    project_dir = Path(project)
                    print(f"--- keyframe project {idx}/{len(projects)}: {project_dir} ---")
                    print(
                        f"keyframe_mode={zoom_mode} start={start_percent}% end={end_percent}% full_duration={use_full_duration} duration_s={duration_seconds}"
                    )

                    bundle = load_project(project_dir)
                    added_main = apply_zoom_keyframes_to_draft(
                        bundle.main_draft,
                        only_picture=only_picture,
                        start_percent=start_percent,
                        end_percent=end_percent,
                        use_full_duration=use_full_duration,
                        duration_seconds=duration_seconds,
                    )
                    write_json_atomic(bundle.main_draft_path, bundle.main_draft)
                    print(f"main_keyframes_applied={added_main}")

                    for tp in bundle.timeline_draft_paths:
                        d = bundle.timelines[tp]
                        added_tl = apply_zoom_keyframes_to_draft(
                            d,
                            only_picture=only_picture,
                            start_percent=start_percent,
                            end_percent=end_percent,
                            use_full_duration=use_full_duration,
                            duration_seconds=duration_seconds,
                        )
                        write_json_atomic(tp, d)
                        print(f"timeline={tp} keyframes_applied={added_tl}")
        except Exception:
            output_buf.write(traceback.format_exc())
            overall_code = 1

        out = output_buf.getvalue()
        if out:
            self.log_queue.put(out)
        self.log_queue.put(f"PROCESS_EXIT:{overall_code}")

    def _on_sync_audio(self) -> None:
        self.mode_var.set("sync")
        self._start_run()

    def _on_pick_project_list_region(self) -> None:
        """Khoanh vùng list project bằng kéo chuột kiểu screenshot, rồi tự điền L/T/W/H."""
        try:
            session = CapCutSessionController(title_hint="CapCut")
            hwnd = session.find_main_window()
            if not hwnd:
                messagebox.showerror("Không thấy CapCut", "Không tìm thấy cửa sổ CapCut đang mở.")
                return

            session.apply_window_policy(hwnd, WindowPolicy(mode="maximize"))
            time.sleep(0.2)

            user32 = ctypes.windll.user32
            r = ctypes.wintypes.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
                messagebox.showerror("Lỗi toạ độ", "Không lấy được toạ độ cửa sổ CapCut.")
                return

            win_left, win_top, win_right, win_bottom = int(r.left), int(r.top), int(r.right), int(r.bottom)
            win_w = max(1, win_right - win_left)
            win_h = max(1, win_bottom - win_top)

            # ép CapCut lên foreground trước khi cho khoanh vùng
            fg_ok = False
            try:
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                deadline_focus = time.time() + 3.0
                while time.time() < deadline_focus:
                    if int(user32.GetForegroundWindow()) == int(hwnd):
                        fg_ok = True
                        break
                    user32.SetForegroundWindow(hwnd)
                    time.sleep(0.08)
            except Exception:
                fg_ok = False

            if not fg_ok:
                messagebox.showerror("CapCut chưa sẵn sàng", "Vui lòng đưa cửa sổ CapCut lên trước rồi bấm Khoanh vùng lại.")
                return

            overlay = tk.Toplevel(self.root)
            overlay.title("Khoanh vùng danh sách dự án")
            overlay.configure(bg="black")
            overlay.attributes("-topmost", True)
            try:
                overlay.attributes("-alpha", 0.22)
            except Exception:
                pass
            overlay.geometry(f"{win_w}x{win_h}+{win_left}+{win_top}")
            overlay.resizable(False, False)

            canvas = tk.Canvas(overlay, bg="black", highlightthickness=0, cursor="cross")
            canvas.pack(fill="both", expand=True)

            hint = "Kéo chuột khoanh vùng list project trong cửa sổ CapCut | Esc: huỷ"
            canvas.create_text(16, 16, anchor="nw", fill="#ffffff", text=hint, font=("Segoe UI", 10, "bold"))

            state = {"x0": None, "y0": None, "rect": None, "result": None}

            def on_press(event):
                state["x0"], state["y0"] = event.x, event.y
                if state["rect"] is not None:
                    canvas.delete(state["rect"])
                state["rect"] = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="#22d3ee", width=2)

            def on_drag(event):
                if state["rect"] is None or state["x0"] is None or state["y0"] is None:
                    return
                canvas.coords(state["rect"], state["x0"], state["y0"], event.x, event.y)

            def finish_selection(event=None):
                if state["x0"] is None or state["y0"] is None:
                    return
                x2 = event.x if event is not None else overlay.winfo_pointerx() - win_left
                y2 = event.y if event is not None else overlay.winfo_pointery() - win_top
                left_local, right_local = sorted((int(state["x0"]), int(x2)))
                top_local, bottom_local = sorted((int(state["y0"]), int(y2)))
                if (right_local - left_local) < 12 or (bottom_local - top_local) < 12:
                    self._set_status("Vùng khoanh quá nhỏ", "error")
                    return
                state["result"] = (
                    win_left + left_local,
                    win_top + top_local,
                    win_left + right_local,
                    win_top + bottom_local,
                )
                overlay.destroy()

            def on_release(event):
                finish_selection(event)

            def on_cancel(_event=None):
                state["result"] = None
                overlay.destroy()

            canvas.bind("<ButtonPress-1>", on_press)
            canvas.bind("<B1-Motion>", on_drag)
            canvas.bind("<ButtonRelease-1>", on_release)
            overlay.bind("<Escape>", on_cancel)
            overlay.bind("<ButtonPress-3>", on_cancel)

            overlay.focus_force()
            self.root.wait_window(overlay)

            if not state["result"]:
                self._set_status("Đã huỷ khoanh vùng", "info")
                return

            sel_l, sel_t, sel_r, sel_b = state["result"]
            # clamp theo cửa sổ CapCut
            sel_l = max(win_left, min(win_right - 1, sel_l))
            sel_t = max(win_top, min(win_bottom - 1, sel_t))
            sel_r = max(win_left + 1, min(win_right, sel_r))
            sel_b = max(win_top + 1, min(win_bottom, sel_b))

            l_ratio = (sel_l - win_left) / win_w
            t_ratio = (sel_t - win_top) / win_h
            w_ratio = (sel_r - sel_l) / win_w
            h_ratio = (sel_b - sel_t) / win_h

            self.export_list_left_var.set(f"{l_ratio:.4f}")
            self.export_list_top_var.set(f"{t_ratio:.4f}")
            self.export_list_width_var.set(f"{w_ratio:.4f}")
            self.export_list_height_var.set(f"{h_ratio:.4f}")
            self._append_log(
                f"[REGION_PICK] list=L{l_ratio:.4f},T{t_ratio:.4f},W{w_ratio:.4f},H{h_ratio:.4f} (px={sel_l},{sel_t},{sel_r},{sel_b})\n"
            )
            self._set_status("Đã khoanh vùng danh sách dự án", "success")
        except Exception as exc:
            messagebox.showerror("Khoanh vùng lỗi", str(exc))

    def _on_test_click_first_project(self) -> None:
        """Interactive debug: click ô project đầu tiên trong grid CapCut để user quan sát trực tiếp."""
        try:
            backend = PyAutoGUIBackend(pause_seconds=0.04)
            session = CapCutSessionController(title_hint="CapCut")
            hwnd = session.find_main_window()
            if not hwnd:
                messagebox.showerror("Không thấy CapCut", "Không tìm thấy cửa sổ CapCut đang mở.")
                return

            session.apply_window_policy(hwnd, WindowPolicy(mode="maximize"))
            time.sleep(0.2)

            rect_obj = ctypes.wintypes.RECT()
            user32 = ctypes.windll.user32
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect_obj)):
                messagebox.showerror("Lỗi toạ độ", "Không lấy được toạ độ cửa sổ CapCut.")
                return
            rect = WindowRect(rect_obj.left, rect_obj.top, rect_obj.right, rect_obj.bottom)
            x = int(rect.left + rect.width * 0.20)
            y = int(rect.top + rect.height * 0.24)

            backend.click_abs(x, y, clicks=2)
            self._append_log(f"[TEST_CLICK] first_project_grid_click_at={x},{y} rect={rect.left},{rect.top},{rect.right},{rect.bottom}\n")
            self._set_status(f"Đã test click tại ({x},{y})", "info")
        except Exception as exc:
            messagebox.showerror("Test click lỗi", str(exc))

    def _on_export_selected_projects(self) -> None:
        if self.current_process is not None or self.current_task_running:
            messagebox.showwarning("Đang bận", "Đang có tiến trình chạy. Vui lòng chờ xong.")
            return

        selected_projects = self._collect_selected_projects()
        if not selected_projects:
            messagebox.showerror("Chưa chọn dự án", "Vui lòng chọn ít nhất 1 dự án trong danh sách.")
            return
        if not self._confirm_bulk_action("xuất bản", selected_projects):
            return

        project_names = [Path(p).name for p in selected_projects]
        self.current_action = "export_publish"
        self._append_log("\n--- Xuất bản project đã chọn ---\n")
        self._append_log(f"projects={len(project_names)} mode=auto_export\n")
        self._set_status(f"Đang xuất bản {len(project_names)} dự án đã chọn...", "info")
        self._set_running_state(True)
        self.current_task_running = True

        threading.Thread(
            target=self._execute_export_selected_projects,
            args=(project_names,),
            daemon=True,
        ).start()

    def _execute_export_selected_projects(self, project_names: list[str]) -> None:
        output_buf = io.StringIO()
        overall_code = 0

        try:
            with contextlib.redirect_stdout(output_buf):
                backend = PyAutoGUIBackend(pause_seconds=0.07)
                session = CapCutSessionController(title_hint="CapCut")
                navigator = ProjectNavigator(
                    backend,
                    ProjectNavigationConfig(
                        result_click_x_ratio=0.23,
                        result_click_y_ratio=0.30,
                        esc_reset_count=3,
                        after_open_wait_seconds=2.5,
                        after_search_wait_seconds=0.0,
                        retries=3,
                        result_open_clicks=3,
                        list_left_ratio=self._safe_ratio(self.export_list_left_var, 0.08),
                        list_top_ratio=self._safe_ratio(self.export_list_top_var, 0.16),
                        list_width_ratio=self._safe_ratio(self.export_list_width_var, 0.84),
                        list_height_ratio=self._safe_ratio(self.export_list_height_var, 0.76),
                        first_card_x_ratio=self._safe_ratio(self.export_grid_first_x_var, 0.14),
                        first_card_y_ratio=self._safe_ratio(self.export_grid_first_y_var, 0.16),
                        card_x_gap_ratio=self._safe_ratio(self.export_grid_gap_x_var, 0.29),
                        card_y_gap_ratio=self._safe_ratio(self.export_grid_gap_y_var, 0.23),
                    ),
                )
                exporter = ExportActionRunner(
                    backend,
                    ExportActionConfig(
                        export_btn_x_ratio=0.93,
                        export_btn_y_ratio=0.06,
                        confirm_btn_x_ratio=0.83,
                        confirm_btn_y_ratio=0.90,
                        search_retries=3,
                        click_retries=2,
                        post_export_wait_seconds=1.0,
                        post_confirm_wait_seconds=1.2,
                    ),
                )
                watcher = ExportProgressWatcher(
                    backend,
                    ExportProgressConfig(
                        timeout_seconds=60.0 * 6.0,
                        poll_interval_seconds=1.0,
                        max_wait_without_template_seconds=8.0,
                    ),
                )
                runner = BatchExportRunner(
                    session=session,
                    navigator=navigator,
                    exporter=exporter,
                    watcher=watcher,
                    backend=backend,
                    exe_candidates=default_capcut_exe_candidates(),
                    logger=print,
                )

                results = runner.run(
                    BatchExportConfig(
                        project_names=project_names,
                        window_policy=WindowPolicy(mode="maximize"),
                        relaunch_each_project=True,
                        launch_timeout_seconds=25.0,
                        close_wait_seconds=3.0,
                        screenshot_on_fail_dir=str(BASE_DIR / "export_failshots"),
                    )
                )

                # Nếu toàn bộ fail ở navigate/progress thì báo rõ để user thấy ngay,
                # tránh cảm giác treo loading im lặng.
                if results and all((not r.success) for r in results):
                    first = results[0]
                    print(
                        f"ERROR_HINT: first_failure_stage={first.stage} message={first.message}"
                    )

                success_count = sum(1 for r in results if r.success)
                fail_count = len(results) - success_count
                print("--- export summary ---")
                print(f"total={len(results)} success={success_count} fail={fail_count}")
                for r in results:
                    print(
                        f"project={r.project_name} success={int(r.success)} stage={r.stage} elapsed={r.elapsed_seconds:.1f}s message={r.message}"
                    )

                if fail_count > 0:
                    overall_code = 1

        except Exception:
            output_buf.write(traceback.format_exc())
            overall_code = 1

        out = output_buf.getvalue()
        if out:
            self.log_queue.put(out)
        self.log_queue.put(f"PROCESS_EXIT:{overall_code}")

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
        if not self._confirm_bulk_action("đồng bộ", selected_projects):
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
                args=(
                    selected_projects,
                    images,
                    voices,
                    mode,
                    self.backup_var.get(),
                    self.transition_enable_var.get(),
                    self.transition_effects_var.get().strip(),
                ),
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

        if self.transition_enable_var.get():
            cmd.extend(["--transition-mode", "random"])
            if self.transition_effects_var.get().strip():
                cmd.extend(["--transition-effects", self.transition_effects_var.get().strip()])
        self._append_log("$ " + " ".join(cmd) + "\n")
        threading.Thread(target=self._execute_command, args=(cmd,), daemon=True).start()

    def refresh_projects(self) -> None:
        if self.projects_container is None:
            return

        for child in self.projects_container.winfo_children():
            child.destroy()
        self.project_items = []

        if not DEFAULT_CAPCUT_PROJECT_ROOT.exists():
            self.project_stats_var.set(self._t("projects_selected", selected=0, total=0))
            self._append_log(
                f'Không tìm thấy thư mục dự án mặc định "{DEFAULT_CAPCUT_PROJECT_ROOT}".\n'
            )
            self._set_status("Không tìm thấy thư mục dự án CapCut", "warning")
            return

        entries = sorted(
            (item for item in DEFAULT_CAPCUT_PROJECT_ROOT.iterdir() if item.is_dir()),
            key=lambda p: (-p.stat().st_mtime, p.name.lower()),
        )
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
            self.project_stats_var.set(self._t("projects_selected", selected=0, total=0))
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
        self,
        projects: list[str],
        images: str,
        voices: str,
        mode: str,
        backup: bool,
        transition_enabled: bool,
        transition_effects: str,
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
                        transition_mode="random" if transition_enabled else "none",
                        transition_effects=transition_effects,
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
        is_transition_apply = self.current_action == "transition_apply"
        is_keyframe_apply = self.current_action == "keyframe_apply"
        is_mask_apply = self.current_action == "mask_apply"
        is_export_publish = self.current_action == "export_publish"

        if is_batch:
            success_title = "Tạo batch xong"
            success_message = "Đã tạo project hàng loạt thành công."
            error_title = "Tạo batch lỗi"
            ok_status = "Tạo batch thành công"
            err_status = f"Tạo batch lỗi (mã {return_code})"
        elif is_transition_apply:
            success_title = "Thêm transition xong"
            success_message = "Đã thêm transition cho các dự án đã chọn."
            error_title = "Thêm transition lỗi"
            ok_status = "Thêm transition thành công"
            err_status = f"Thêm transition lỗi (mã {return_code})"
        elif is_keyframe_apply:
            success_title = "Thêm keyframe xong"
            success_message = "Đã thêm keyframe zoom cho các dự án đã chọn."
            error_title = "Thêm keyframe lỗi"
            ok_status = "Thêm keyframe thành công"
            err_status = f"Thêm keyframe lỗi (mã {return_code})"
        elif is_mask_apply:
            success_title = "Áp dụng mask xong"
            success_message = "Đã áp dụng mask cho các dự án đã chọn."
            error_title = "Áp dụng mask lỗi"
            ok_status = "Áp dụng mask thành công"
            err_status = f"Áp dụng mask lỗi (mã {return_code})"
        elif is_export_publish:
            success_title = "Xuất bản xong"
            success_message = "Đã xuất bản các dự án đã chọn."
            error_title = "Xuất bản lỗi"
            ok_status = "Xuất bản thành công"
            err_status = f"Xuất bản lỗi (mã {return_code})"
        else:
            success_title = "Đồng bộ xong"
            success_message = "Đã đồng bộ các dự án đã chọn thành công."
            error_title = "Đồng bộ lỗi"
            ok_status = "Đồng bộ thành công"
            err_status = f"Đồng bộ lỗi (mã {return_code})"

        if return_code == 0:
            self._set_status(ok_status, "success")
            self._show_toast(success_title, success_message, "success")
            messagebox.showinfo(success_title, success_message)
        else:
            self._set_status(err_status, "error")
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
        if self.export_publish_button is not None:
            self.export_publish_button.configure(state=new_state)
        if self.test_click_button is not None:
            self.test_click_button.configure(state=new_state)
        if self.pick_region_button is not None:
            self.pick_region_button.configure(state=new_state)
        if self.batch_button is not None:
            self.batch_button.configure(state=new_state)
        if self.apply_transition_button is not None:
            self.apply_transition_button.configure(state=new_state)
        if self.apply_keyframe_button is not None:
            self.apply_keyframe_button.configure(state=new_state)
        if self.apply_mask_button is not None:
            self.apply_mask_button.configure(state=new_state)

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
