#!/usr/bin/env python3
"""Tkinter/ttk GUI wrapper for the CapCut adapter CLI."""

from __future__ import annotations

import contextlib
import io
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import EW, NSEW, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from cli import run_inspect, run_sync

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
        self.root.title("CapCut Sync v1.6 (build v11)")
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

        # Keep vars for internal compatibility/fallback, but UI remains grid-first.
        self.images_var = tk.StringVar()
        self.voices_var = tk.StringVar()
        self.mode_var = tk.StringVar(value="sync")
        self.backup_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Ready · Refresh projects, select from grid, then Sync")

        self.project_items: list[tuple[str, str, tk.BooleanVar, ttk.Checkbutton]] = []
        self.project_search_var = tk.StringVar()
        self.project_stats_var = tk.StringVar(value="0 selected")

        self.projects_canvas: tk.Canvas | None = None
        self.projects_container: ttk.Frame | None = None
        self.projects_canvas_window: int | None = None
        self.projects_scroll: ttk.Scrollbar | None = None
        self.refresh_button: ttk.Button | None = None
        self.inspect_button: ttk.Button | None = None
        self.sync_button: ttk.Button | None = None
        self.select_all_button: ttk.Button | None = None
        self.clear_all_button: ttk.Button | None = None
        self.progress_bar: ttk.Progressbar | None = None
        self.status_badge: ttk.Label | None = None
        self.status_label: ttk.Label | None = None

        self._build_layout()
        self._wire_events()

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

        ttk.Label(header, text="CapCut Project Sync", style="AppTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="Refresh → filter/select projects → Inspect/Sync",
            style="Subtle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        left_panel = ttk.Frame(main_frame, style="Panel.TFrame")
        left_panel.grid(row=1, column=0, sticky=NSEW, padx=(0, 14))
        left_panel.columnconfigure(0, weight=1)
        left_panel.rowconfigure(1, weight=1)

        action_card = ttk.Labelframe(
            left_panel,
            text="Actions",
            padding=14,
            style="ProjectCard.TLabelframe",
        )
        action_card.grid(row=0, column=0, sticky=EW)
        action_card.columnconfigure(2, weight=1)

        ttk.Label(action_card, text="Quick flow", style="SectionTitle.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        ttk.Label(
            action_card,
            text="Run a safe Inspect first, then Sync once output looks good.",
            style="Subtle.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 12))

        self.refresh_button = ttk.Button(
            action_card,
            text="Refresh",
            command=self.refresh_projects,
            width=12,
            style="Secondary.TButton",
        )
        self.refresh_button.grid(row=2, column=0, sticky="w")

        self.inspect_button = ttk.Button(
            action_card,
            text="Inspect",
            command=self._on_inspect_audio,
            width=12,
            style="Secondary.TButton",
        )
        self.inspect_button.grid(row=2, column=1, sticky="w", padx=(8, 0))

        self.sync_button = ttk.Button(
            action_card,
            text="Sync",
            command=self._on_sync_audio,
            width=12,
            style="Accent.TButton",
        )
        self.sync_button.grid(row=2, column=2, sticky="w", padx=(8, 0))

        ttk.Label(
            action_card,
            text=f"CapCut root: {DEFAULT_CAPCUT_PROJECT_ROOT}",
            style="Subtle.TLabel",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))

        projects_card = ttk.Labelframe(
            left_panel,
            text="Projects",
            padding=12,
            style="ProjectCard.TLabelframe",
        )
        projects_card.grid(row=1, column=0, sticky=NSEW, pady=(14, 0))
        projects_card.columnconfigure(0, weight=1)
        projects_card.rowconfigure(2, weight=1)

        toolbar = ttk.Frame(projects_card, style="Panel.TFrame")
        toolbar.grid(row=0, column=0, sticky=EW, pady=(0, 8))
        toolbar.columnconfigure(1, weight=1)

        ttk.Label(toolbar, text="Find:", style="Subtle.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        search_entry = ttk.Entry(toolbar, textvariable=self.project_search_var, style="Search.TEntry")
        search_entry.grid(row=0, column=1, sticky=EW)

        self.select_all_button = ttk.Button(
            toolbar,
            text="All",
            command=self._select_all_projects,
            style="Ghost.TButton",
            width=6,
        )
        self.select_all_button.grid(row=0, column=2, sticky="e", padx=(8, 4))

        self.clear_all_button = ttk.Button(
            toolbar,
            text="Clear",
            command=self._clear_all_projects,
            style="Ghost.TButton",
            width=6,
        )
        self.clear_all_button.grid(row=0, column=3, sticky="e")

        ttk.Label(
            projects_card,
            textvariable=self.project_stats_var,
            style="Subtle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(0, 8))

        list_host = ttk.Frame(projects_card, style="Panel.TFrame")
        list_host.grid(row=2, column=0, sticky=NSEW)
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
            text="Run Log",
            padding=12,
            style="ProjectCard.TLabelframe",
        )
        log_card.grid(row=0, column=0, sticky=NSEW)
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(1, weight=1)

        ttk.Label(
            log_card,
            text="Live inspect/sync output + errors.",
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

        self.status_badge = ttk.Label(status_card, text="READY", style="Badge.TLabel")
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
        self.project_search_var.trace_add("write", self._on_search_change)

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

    def _select_all_projects(self, _event=None):
        for _, _, var, _ in self.project_items:
            var.set(True)
        self._update_project_stats()
        return "break"

    def _clear_all_projects(self, _event=None):
        for _, _, var, _ in self.project_items:
            var.set(False)
        self._update_project_stats()
        return "break"

    def _on_search_change(self, *_args) -> None:
        self._apply_project_filter()

    def _toggle_project(self) -> None:
        self._update_project_stats()

    def _apply_project_filter(self) -> None:
        if self.projects_container is None:
            return

        keyword = self.project_search_var.get().strip().lower()
        visible_row = 0
        visible_count = 0

        for _, name, _, widget in self.project_items:
            show = keyword in name.lower() if keyword else True
            if show:
                widget.grid(row=visible_row, column=0, sticky=EW, pady=(0, 2))
                visible_row += 1
                visible_count += 1
            else:
                widget.grid_remove()

        self._update_project_stats(visible_count=visible_count)
        self._on_projects_container_configure()

    def _update_project_stats(self, visible_count: int | None = None) -> None:
        total = len(self.project_items)
        selected = sum(1 for _, _, var, _ in self.project_items if var.get())
        visible = visible_count if visible_count is not None else sum(1 for _, _, _, widget in self.project_items if widget.winfo_manager())
        self.project_stats_var.set(f"Selected {selected}/{total} · Visible {visible}")

    def _collect_selected_projects(self) -> list[str]:
        out: list[str] = []
        for path, _, var, _ in self.project_items:
            if var.get():
                out.append(path)
        return sorted(out)

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

    def _on_inspect_audio(self) -> None:
        self.mode_var.set("inspect")
        self._start_run()

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
            messagebox.showerror("No projects selected", "Select at least one CapCut project from the grid.")
            return

        try:
            if images and voices and len(selected_projects) == 1:
                images, voices = self._resolve_media_dirs(selected_projects[0], images, voices)
        except Exception as exc:
            messagebox.showerror("Missing media folders", str(exc))
            return

        self._append_log("\n--- Running CLI task ---\n")
        self._append_log(
            f"mode={mode} projects={len(selected_projects)} images={images or '[auto]'} voices={voices or '[auto]'} backup={self.backup_var.get()}\n"
        )
        mode_label = "Inspect" if mode == "inspect" else "Sync"
        self._set_status(f"Running {mode_label} for {len(selected_projects)} selected project(s)...", "info")
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
            self.project_stats_var.set("Selected 0/0 · Visible 0")
            self._append_log(
                f'Default CapCut root "{DEFAULT_CAPCUT_PROJECT_ROOT}" not found. Refresh once Windows volume is available.\n'
            )
            self._set_status("CapCut root not found", "warning")
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
            self._append_log(f"Skipped {skipped} non-project folders from list.\n")

        if not filtered:
            self.project_stats_var.set("Selected 0/0 · Visible 0")
            self._append_log(f"No CapCut projects found inside {DEFAULT_CAPCUT_PROJECT_ROOT}.\n")
            self._set_status("No projects found", "warning")
            return

        for entry in filtered:
            project_var = tk.BooleanVar(value=True)
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

        self._apply_project_filter()
        self._set_status(f"Project list refreshed · {len(filtered)} project(s) ready", "info")

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
                    if mode == "inspect":
                        code = run_inspect(
                            Path(project),
                            Path(resolved_images) if resolved_images else None,
                            Path(resolved_voices) if resolved_voices else None,
                        )
                    else:
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
                if item.startswith("PROCESS_EXIT:"):
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

        if return_code == 0:
            self._set_status("Run completed successfully", "success")
            self._show_toast("Sync complete", "Selected project sync finished successfully.", "success")
            messagebox.showinfo("Sync complete", "Selected project sync finished successfully.")
        else:
            self._set_status(f"Run failed (exit {return_code})", "error")
            self._show_toast("Sync failed", f"Run failed with exit code {return_code}.", "danger")
            messagebox.showerror("Sync failed", f"Run failed with exit code {return_code}. Check the run log.")

        self._append_log(f"\n--- Process exited with code {return_code} ---\n")

    def _set_running_state(self, running: bool) -> None:
        if self.progress_bar is not None:
            if running:
                self.progress_bar.start(10)
            else:
                self.progress_bar.stop()

        new_state = "disabled" if running else "normal"
        if self.sync_button is not None:
            self.sync_button.configure(state=new_state)
        if self.inspect_button is not None:
            self.inspect_button.configure(state=new_state)
        if self.refresh_button is not None:
            self.refresh_button.configure(state=new_state)
        if self.select_all_button is not None:
            self.select_all_button.configure(state=new_state)
        if self.clear_all_button is not None:
            self.clear_all_button.configure(state=new_state)

    def _set_status(self, message: str, status_type: str = "info") -> None:
        self.status_var.set(message)
        badge_text = status_type.upper()
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
                "Stop process?",
                "A CLI run is still running. Stop it and close?",
            ):
                return
            self.current_process.terminate()

        if self.current_task_running:
            if not messagebox.askyesno(
                "Close app?",
                "A task is still running. Close anyway?",
            ):
                return

        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    CapCutGui().run()


if __name__ == "__main__":
    main()
