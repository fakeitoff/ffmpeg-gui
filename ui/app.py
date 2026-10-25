# -*- coding: utf-8 -*-
"""FFmpeg GUI 主窗口。"""
from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from core import probe as probe_mod
from core.probe import FFmpegNotFound, locate
from core.runner import Job, JobRunner, LOG_LEVELS
from core.util import (build_output_in_dir, build_output_name, ext_of, format_time,
                       human_size, local_temp_dir, natural_key, open_in_explorer,
                       purge_dir, purge_stale_temp, same_file)
from . import theme, widgets
from .tabs import TAB_CLASSES

MEDIA_EXTS = {
    ".mp4", ".mkv", ".mov", ".avi", ".flv", ".wmv", ".webm", ".ts", ".m4v", ".mpg",
    ".mpeg", ".3gp", ".rmvb", ".vob", ".ogv", ".rm", ".mts", ".m2ts", ".f4v",
    ".m3u8", ".m3u",
    ".mp3", ".aac", ".wav", ".flac", ".ogg", ".opus", ".m4a", ".wma", ".ac3", ".ape",
    ".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff",
}

LOG_COLORS = {"info": "#3b4148", "cmd": theme.ACCENT, "warn": theme.WARN,
              "error": theme.ERR, "ok": theme.OK, "dim": theme.MUTED}


def _enable_dpi_awareness():
    """必须在创建 Tk 窗口之前调用，否则 Windows 会按 96 DPI 虚拟化整个窗口
    （在 125% / 150% 缩放的屏幕上表现为界面被放大后模糊）。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)   # 系统级 DPI 感知
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()        # 老系统回退
    except Exception:
        pass


def _detect_ui_scale(root) -> float:
    """返回界面缩放系数。可用环境变量 FFGUI_SCALE 强制指定。"""
    env = os.environ.get("FFGUI_SCALE", "").strip()
    if env:
        try:
            return max(0.75, min(3.0, float(env)))
        except ValueError:
            pass
    try:
        return max(1.0, min(2.0, root.winfo_fpixels("1i") / 96.0))
    except Exception:
        return 1.0


class App(tk.Tk):
    """主窗口。"""

    def __init__(self, initial_files=None, initial_tab=None):
        _enable_dpi_awareness()      # 必须早于 Tk 初始化
        super().__init__()
        self._setup_dpi()
        self.title("FFmpeg GUI —— 常用视频音频处理工具箱")
        self.geometry(self._initial_geometry())
        self.minsize(int(880 * self.ui_scale), int(560 * self.ui_scale))

        theme.setup_theme(self)

        # ---- 运行环境 ----
        self.ffmpeg_path = ""
        self.ffprobe_path = ""
        self.startup_error = ""
        try:
            self.ffmpeg_path, self.ffprobe_path = locate()
        except FFmpegNotFound as exc:
            self.startup_error = str(exc)

        # ---- 状态 ----
        self.src_files: list[str] = []
        self.info = None                     # 第一个源文件的 MediaInfo
        self.info_cache: dict[str, object] = {}
        self._pending_probe: str | None = None
        self.runner: JobRunner | None = None
        self._queue: queue.Queue = queue.Queue()
        self._encoders: set[str] | None = None
        self._font_path: str = ""
        self._last_preview = ""
        self._last_output_dir = ""
        self._log_buffer: list[tuple[str, str]] = []
        self._log_dirty = False

        self.log_level = tk.StringVar(value="info")
        self.out_mode = tk.StringVar(value="auto")
        self.out_path = tk.StringVar(value="")
        self.overwrite = tk.BooleanVar(value=True)
        self.status_text = tk.StringVar(value="就绪")
        self.src_summary = tk.StringVar(value="尚未选择文件")
        self.percent_text = tk.StringVar(value="0.0%")

        self._build_ui()
        if initial_tab is not None:
            try:
                self.notebook.select(int(initial_tab))
                self._on_tab_changed()
            except (tk.TclError, ValueError, IndexError):
                pass

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._closing = False
        self._drain_after = self.after(120, self._drain_queue)
        self._preview_after = self.after(600, self._poll_preview)

        if self.startup_error:
            self.log(self.startup_error, "error")
            self.btn_start.configure(state="disabled")
            messagebox.showerror("未找到 FFmpeg", self.startup_error)
        else:
            version = probe_mod.ffmpeg_version(self.ffmpeg_path)
            self.log(f"已就绪 · {version}", "ok")
            self.log(f"可执行文件：{self.ffmpeg_path}", "dim")
            if self.ffprobe_path == self.ffmpeg_path:
                # locate() 找不到 ffprobe 时会退回 ffmpeg：转码照样能跑，
                # 但读不到时长/帧数，界面信息栏一片空白、进度条只能滚动。
                self.log("未找到 ffprobe（同目录下的 ffprobe.exe）：媒体信息与进度百分比将不可用，"
                         "请安装包含 ffprobe 的完整版 ffmpeg。", "warn")

        if initial_files:
            self.add_files([f for f in initial_files if os.path.isfile(f)])

        # 清理临时文件：新版放在程序目录的 temp/ 下，此处回收历史残留
        try:
            removed = purge_stale_temp(24.0)
            removed += purge_dir(local_temp_dir(), 12.0)
            if removed:
                self.log(f"已清理 {removed} 个历史遗留的临时文件", "dim")
        except Exception:
            pass

    # ==================================================================
    # 界面
    # ==================================================================
    def _setup_dpi(self):
        """让界面在高分屏下保持清晰，并按系统缩放比例调整字号。"""
        self.ui_scale = _detect_ui_scale(self)
        try:
            self.tk.call("tk", "scaling", 96.0 / 72.0 * self.ui_scale)
        except Exception:
            pass

    def _initial_geometry(self) -> str:
        """按屏幕大小自适应窗口尺寸，避免在小屏上被裁切。"""
        s = self.ui_scale
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
        except tk.TclError:
            return f"{int(1180 * s)}x{int(880 * s)}"
        # 小屏（如 1366×768 / 1536×864）上按可用空间收缩，避免溢出屏幕
        w = min(int(1180 * s), sw - int(50 * s))
        h = min(int(880 * s), sh - int(80 * s))
        w = max(w, int(820 * s))
        h = max(h, int(520 * s))
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 3)
        return f"{w}x{h}+{x}+{y}"

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        self._build_topbar()
        self._build_source_card()

        paned = ttk.PanedWindow(self, orient="vertical")
        paned.grid(row=2, column=0, sticky="nsew", padx=10, pady=(6, 8))
        self.paned = paned

        self.notebook = ttk.Notebook(paned)
        paned.add(self.notebook, weight=3)
        self.tabs = []
        for cls in TAB_CLASSES:
            tab = cls(self.notebook, self)
            self.notebook.add(tab, text=cls.name)
            self.tabs.append(tab)
        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self._on_tab_changed())

        bottom = ttk.Frame(paned, style="Panel.TFrame")
        paned.add(bottom, weight=2)
        self._build_bottom(bottom)

        # 首次显示时把分隔条放到 62% 的位置，保证选项区与日志区都有合理空间
        self._sash_done = False
        paned.bind("<Configure>", self._place_sash)

    def _place_sash(self, _event=None):
        if self._sash_done:
            return
        try:
            h = self.paned.winfo_height()
            if h > 240:
                self.paned.sashpos(0, int(h * 0.62))
                self._sash_done = True
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    def _build_topbar(self):
        bar = ttk.Frame(self, style="TFrame")
        bar.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 0))
        bar.columnconfigure(1, weight=1)

        ttk.Label(bar, text="FFmpeg GUI", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(bar, text="常用音视频处理工具箱", style="Muted.TLabel").grid(
            row=0, column=1, sticky="w", padx=(10, 0))

        status = "● ffmpeg 已就绪" if not self.startup_error else "● 未找到 ffmpeg"
        color = theme.OK if not self.startup_error else theme.ERR
        lbl = tk.Label(bar, text=status, bg=theme.BG, fg=color, font=(theme.FONT, 9, "bold"))
        lbl.grid(row=0, column=4, padx=(14, 0))
        if self.ffmpeg_path:
            lbl.bind("<Enter>", lambda e: lbl.configure(text=self.ffmpeg_path))
            lbl.bind("<Leave>", lambda e: lbl.configure(text=status))

    # ------------------------------------------------------------------
    def _build_source_card(self):
        card = ttk.Frame(self, style="Card.TFrame", padding=(12, 10))
        card.grid(row=1, column=0, sticky="ew", padx=10, pady=(8, 0))
        card.columnconfigure(1, weight=1)

        # -- 源文件 --
        ttk.Label(card, text="源文件", style="Panel.TLabel", font=(theme.FONT, 10, "bold")).grid(
            row=0, column=0, sticky="nw", padx=(0, 10))

        src_box = ttk.Frame(card, style="Panel.TFrame")
        src_box.grid(row=0, column=1, sticky="ew")
        src_box.columnconfigure(0, weight=1)

        list_holder = ttk.Frame(src_box, style="Panel.TFrame")
        list_holder.grid(row=0, column=0, sticky="ew")
        list_holder.columnconfigure(0, weight=1)
        self.src_list = tk.Listbox(list_holder, height=2, selectmode="extended",
                                   bg="#ffffff", fg=theme.TEXT, relief="solid", borderwidth=1,
                                   font=(theme.FONT, 9), activestyle="none",
                                   selectbackground="#dbe6fd", selectforeground=theme.TEXT,
                                   highlightthickness=0)
        self.src_list.grid(row=0, column=0, sticky="ew")
        sb = ttk.Scrollbar(list_holder, orient="vertical", command=self.src_list.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.src_list.configure(yscrollcommand=sb.set)

        btns = ttk.Frame(src_box, style="Panel.TFrame")
        btns.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        for text, cmd, width in (("添加文件…", self.pick_files, 10),
                                 ("添加文件夹…", self.pick_folder, 11),
                                 ("移除选中", self.remove_selected, 10),
                                 ("清空", self.clear_files, 7),
                                 ("↑", self.move_up, 3),
                                 ("↓", self.move_down, 3)):
            ttk.Button(btns, text=text, command=cmd, width=width).pack(side="left", padx=(0, 4))

        self.src_info = ttk.Label(src_box, textvariable=self.src_summary,
                                  style="PanelMuted.TLabel")
        self.src_info.grid(row=2, column=0, sticky="w", pady=(5, 0))

        # -- 输出 --
        ttk.Label(card, text="输出位置", style="Panel.TLabel", font=(theme.FONT, 10, "bold")).grid(
            row=1, column=0, sticky="nw", padx=(0, 10), pady=(12, 0))

        out_box = ttk.Frame(card, style="Panel.TFrame")
        out_box.grid(row=1, column=1, sticky="ew", pady=(12, 0))
        out_box.columnconfigure(0, weight=1)

        radios = ttk.Frame(out_box, style="Panel.TFrame")
        radios.grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(radios, text="源文件同目录，自动命名", value="auto",
                        variable=self.out_mode, command=self._on_out_mode).pack(side="left")
        ttk.Radiobutton(radios, text="指定位置", value="custom",
                        variable=self.out_mode, command=self._on_out_mode).pack(side="left", padx=(16, 0))

        self.out_entry = ttk.Entry(out_box, textvariable=self.out_path)
        self.out_entry.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.out_browse = ttk.Button(out_box, text="浏览…", width=8, command=self._pick_output)
        self.out_browse.grid(row=1, column=1, padx=(6, 0), pady=(6, 0))

        self.out_hint = ttk.Label(out_box, text="", style="PanelMuted.TLabel")
        self.out_hint.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Checkbutton(out_box, text="覆盖已存在的同名文件（不勾选时遇到同名文件会中止）",
                        variable=self.overwrite).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self._on_out_mode()

    # ------------------------------------------------------------------
    def _build_bottom(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(4, weight=1)

        head = ttk.Frame(parent, style="Panel.TFrame")
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 4))
        head.columnconfigure(1, weight=1)
        ttk.Label(head, text="命令行预览", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(head, text="  （随选项实时更新，可复制后自行使用）",
                  style="PanelMuted.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(head, text="日志级别", style="PanelMuted.TLabel").grid(row=0, column=2, padx=(0, 4))
        ttk.Combobox(head, textvariable=self.log_level, values=LOG_LEVELS, width=8,
                     state="readonly").grid(row=0, column=3, padx=(0, 8))
        ttk.Button(head, text="复制命令", style="Ghost.TButton",
                   command=self._copy_command).grid(row=0, column=4, padx=(4, 0))
        ttk.Button(head, text="清空日志", style="Ghost.TButton",
                   command=self._clear_log).grid(row=0, column=5, padx=(4, 0))

        self.cmd_text = tk.Text(parent, height=3, wrap="word", bg="#fbfbfc", fg=theme.ACCENT,
                                relief="solid", borderwidth=1, font=(theme.MONO, 9),
                                padx=8, pady=5, state="disabled")
        self.cmd_text.grid(row=1, column=0, sticky="ew", padx=12)

        prog = ttk.Frame(parent, style="Panel.TFrame")
        prog.grid(row=2, column=0, sticky="ew", padx=12, pady=(8, 2))
        prog.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(prog, style="Thin.Horizontal.TProgressbar",
                                        mode="determinate", maximum=100)
        self.progress.grid(row=0, column=0, sticky="ew")
        ttk.Label(prog, textvariable=self.percent_text, style="Form.TLabel",
                  width=7, anchor="e").grid(row=0, column=1, padx=(10, 12))

        self.btn_cancel = ttk.Button(prog, text="停止", style="Danger.TButton",
                                     command=self.on_cancel, state="disabled")
        self.btn_cancel.grid(row=0, column=2, padx=(0, 6))
        self.btn_open = ttk.Button(prog, text="打开输出位置", command=self._open_output)
        self.btn_open.grid(row=0, column=3, padx=(0, 6))
        self.btn_start = ttk.Button(prog, text="▶  开始处理", style="Accent.TButton",
                                    command=self.on_start)
        self.btn_start.grid(row=0, column=4)

        ttk.Label(parent, textvariable=self.status_text, style="PanelMuted.TLabel",
                  anchor="w").grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 4))

        self.log_panel = widgets.LogPanel(parent)
        self.log_panel.grid(row=4, column=0, sticky="nsew", padx=12, pady=(0, 10))
        self.log_panel.text.configure(height=6)

    # ==================================================================
    # 环境
    # ==================================================================
    @property
    def encoders(self) -> set[str]:
        if self._encoders is None:
            self._encoders = probe_mod.available_encoders(self.ffmpeg_path) if self.ffmpeg_path else set()
        return self._encoders

    @property
    def font_path(self) -> str:
        if not self._font_path:
            self._font_path = probe_mod.pick_font()
        return self._font_path

    def get_info(self, path: str, refresh: bool = False):
        """带缓存的 ffprobe 调用；失败返回 None。

        ``refresh=True`` 强制重新探测（真正开工前使用，避免用到过期或失败的缓存）。
        """
        if not refresh and path in self.info_cache:
            return self.info_cache[path]
        try:
            result = probe_mod.probe(self.ffprobe_path, path)
        except Exception:
            result = None
        if result is not None:
            self.info_cache[path] = result
        elif not refresh:
            # 失败的探测结果也缓存，避免命令行预览反复重试拖慢界面
            self.info_cache[path] = None
        return result

    def probe_ok(self, path: str) -> bool:
        return self.get_info(path) is not None

    # ==================================================================
    # 源文件管理
    # ==================================================================
    def pick_files(self):
        files = widgets.ask_open_files(self, widgets.MEDIA_TYPES, multiple=True,
                                       initialdir=os.path.dirname(self.src_files[0]) if self.src_files else None)
        if files:
            self.add_files(files)

    def pick_folder(self):
        d = filedialog.askdirectory(title="选择包含媒体文件的文件夹")
        if not d:
            return
        files = []
        for name in sorted(os.listdir(d), key=natural_key):
            full = os.path.join(d, name)
            if os.path.isfile(full) and ext_of(full) and f".{ext_of(full)}" in MEDIA_EXTS:
                files.append(full)
        if not files:
            messagebox.showinfo("提示", "该文件夹内没有找到可识别的媒体文件。")
            return
        self.add_files(files)

    def add_files(self, files):
        added = 0
        for f in files:
            f = os.path.abspath(f)
            if f not in self.src_files:
                self.src_files.append(f)
                added += 1
        if added:
            self._refresh_src_list()
            self.log(f"已添加 {added} 个文件，共 {len(self.src_files)} 个。", "dim")

    def remove_selected(self):
        sel = sorted(self.src_list.curselection(), reverse=True)
        for i in sel:
            if 0 <= i < len(self.src_files):
                self.src_files.pop(i)
        self._refresh_src_list()

    def clear_files(self):
        self.src_files.clear()
        self._refresh_src_list()

    def move_up(self):
        self._move_selected(-1)

    def move_down(self):
        self._move_selected(1)

    def _move_selected(self, delta: int):
        """把选中的整段向前/向后挪一格，段内顺序保持不变。

        逐个交换会让相邻的多个选中项互相越位（原来 [C,D] 上移变成 [D,C]），
        所以按移动方向决定遍历顺序：上移从前往后，下移从后往前。
        """
        sel = list(self.src_list.curselection())
        if not sel:
            return
        if min(sel) + delta < 0 or max(sel) + delta >= len(self.src_files):
            return
        order = sel if delta < 0 else list(reversed(sel))
        moved = set()
        for i in order:
            j = i + delta
            self.src_files[i], self.src_files[j] = self.src_files[j], self.src_files[i]
            moved.add(j)
        self._refresh_src_list()
        for i in sorted(moved):
            self.src_list.selection_set(i)

    def _refresh_src_list(self):
        self.src_list.delete(0, "end")
        for path in self.src_files:
            self.src_list.insert("end", path)
        count = len(self.src_files)
        if count == 0:
            self.src_summary.set("尚未选择文件")
            self.info = None
        else:
            self.src_summary.set(f"共 {count} 个文件" + ("（将批量处理）" if count > 1 else ""))
        if count > 1 and self.out_mode.get() == "auto":
            pass  # 自动命名天然支持批量
        self._probe_first()
        self.refresh_auto_output()
        for tab in self.tabs:
            try:
                tab.on_src_changed()
            except Exception:
                pass

    def _probe_first(self):
        if not self.src_files:
            self.info = None
            self.status_text.set("就绪")
            return
        path = self.src_files[0]
        self.status_text.set(f"正在读取媒体信息… {os.path.basename(path)}")

        def work():
            info = self.get_info(path)
            self._queue.put(("probed", path, info))

        threading.Thread(target=work, daemon=True).start()

    def _apply_probe(self, path, info):
        if not self.src_files or self.src_files[0] != path:
            return
        self.info = info
        if info is None:
            self.status_text.set("无法解析该文件（可能不是媒体文件或被占用）")
            self.log(f"ffprobe 无法解析：{path}", "warn")
        else:
            self.status_text.set(f"{os.path.basename(path)}   ·   {info.describe()}")
        for tab in self.tabs:
            try:
                tab.on_src_changed()
            except Exception:
                pass
        self.refresh_auto_output()

    # ==================================================================
    # 输出路径
    # ==================================================================
    def _on_out_mode(self):
        auto = self.out_mode.get() == "auto"
        state = "disabled" if auto else "normal"
        self.out_entry.configure(state=state)
        self.out_browse.configure(state=state)
        if auto:
            self.out_hint.configure(text="输出文件将与源文件放在同一目录，文件名自动加处理后缀。")
        elif len(self.src_files) > 1:
            self.out_hint.configure(text="已选择多个文件：请填写一个【输出目录】。")
        else:
            self.out_hint.configure(text="可填写完整输出文件路径（含文件名与扩展名）。")
        self.refresh_auto_output()

    def _pick_output(self):
        if len(self.src_files) > 1:
            d = filedialog.askdirectory(title="选择输出目录")
            if d:
                self.out_path.set(d)
        else:
            tab = self.current_tab()
            ext = tab.output_ext() if tab else "mp4"
            initial = ""
            if self.src_files:
                initial = build_output_name(self.src_files[0], tab.output_suffix() if tab else "_out", ext)
            path = filedialog.asksaveasfilename(
                title="选择输出文件", defaultextension=f".{ext}",
                initialfile=os.path.basename(initial) if initial else f"output.{ext}",
                initialdir=os.path.dirname(initial) if initial else None)
            if path:
                self.out_path.set(path)

    def refresh_auto_output(self):
        tab = self.current_tab()
        if tab is None:
            return
        if self.out_mode.get() == "auto" and self.src_files:
            name = build_output_name(self.src_files[0], tab.output_suffix(), tab.output_ext())
            self.out_path.set(name)
        elif not self.out_path.get() and self.src_files:
            self.out_path.set(build_output_name(self.src_files[0], tab.output_suffix(), tab.output_ext()))

    def resolve_output(self, src: str, tab) -> str:
        suffix = tab.output_suffix()
        ext = tab.output_ext() or "mp4"
        if self.out_mode.get() == "auto" or not self.out_path.get().strip():
            return build_output_name(src, suffix, ext)
        path = self.out_path.get().strip()
        if len(self.src_files) > 1 or os.path.isdir(path):
            return build_output_in_dir(src, path, suffix, ext)
        return path

    # ==================================================================
    # 标签页
    # ==================================================================
    def current_tab(self):
        if not hasattr(self, "notebook") or not getattr(self, "tabs", None):
            return None
        try:
            idx = self.notebook.index(self.notebook.select())
        except tk.TclError:
            return None
        return self.tabs[idx] if 0 <= idx < len(self.tabs) else None

    def _on_tab_changed(self):
        tab = self.current_tab()
        if tab is None:
            return
        self.btn_start.configure(state="normal" if (tab.runnable and not self.startup_error) else "disabled")
        self._on_out_mode()
        self.refresh_auto_output()
        try:
            tab.on_src_changed()
        except Exception:
            pass

    # ==================================================================
    # 预览 / 日志 / 状态
    # ==================================================================
    def _runner_busy(self) -> bool:
        """当前是否有任务在跑。异常时按“没有在跑”处理，绝不阻塞界面逻辑。"""
        runner = self.runner
        if runner is None:
            return False
        try:
            return bool(runner.is_alive())
        except Exception:
            return False

    def _poll_preview(self):
        if self._closing:
            return
        self._refresh_preview_text()
        self._preview_after = self.after(700, self._poll_preview)

    def _refresh_preview_text(self):
        """重算并显示命令行预览。任何异常都不应影响界面其它逻辑。"""
        try:
            tab = self.current_tab()
            if tab is not None and tab.runnable:
                src = tab.src_override or (self.src_files[0] if self.src_files else "<源文件>")
                dst = self.resolve_output(src, tab) if self.src_files else "<输出文件>"
                try:
                    args = tab.build_cmd(src, dst)
                    # 预览要跟真实执行一致，包括「是否覆盖同名文件」
                    cmd = Job(src, dst, args).preview(
                        self.ffmpeg_path or "ffmpeg", self.log_level.get(),
                        self.overwrite.get())
                except Exception as exc:  # noqa: BLE001
                    cmd = f"（参数暂不完整：{exc}）"
            elif tab is not None:
                cmd = "（当前页面不执行转码）"
            else:
                cmd = ""
            # 任务执行中不覆盖预览，改为提示（执行中的完整命令已打印在日志里）
            if self._runner_busy():
                cmd = "正在执行…（命令行已在上方日志中输出）"
            if cmd != self._last_preview:
                self._last_preview = cmd
                self.cmd_text.configure(state="normal")
                self.cmd_text.delete("1.0", "end")
                self.cmd_text.insert("1.0", cmd)
                self.cmd_text.configure(state="disabled")
        except Exception:
            pass

    def _copy_command(self):
        text = self.cmd_text.get("1.0", "end").strip()
        if text and not text.startswith("（"):
            self.clipboard_clear()
            self.clipboard_append(text)
            self.status_text.set("命令已复制到剪贴板")

    def _clear_log(self):
        self._log_buffer.clear()
        self._log_dirty = False
        self.log_panel.clear()

    def log(self, line: str, kind: str = "info"):
        """写日志。先入缓冲区，由 _drain_queue 每 120ms 批量刷一次 —— 逐行
        直接插入 Text 在长任务里会明显拖慢界面（进度条看起来就像卡住）。"""
        self._log_buffer.append((line, kind))
        if len(self._log_buffer) > 6000:
            del self._log_buffer[:3000]
        self._log_dirty = True

    def _flush_log(self):
        if not self._log_dirty:
            return
        self._log_dirty = False
        items, self._log_buffer = self._log_buffer, []
        try:
            self.log_panel.write_many(items)
        except Exception:
            pass

    def set_hint(self, text: str):
        self.status_text.set(text)

    def _open_output(self):
        target = self._last_output_dir
        if not target:
            tab = self.current_tab()
            if self.src_files and tab:
                target = os.path.dirname(self.resolve_output(self.src_files[0], tab))
            elif self.out_path.get():
                target = self.out_path.get()
        if not target:
            return
        if not os.path.exists(target):
            messagebox.showinfo("提示", f"路径尚不存在：\n{target}")
            return
        try:
            open_in_explorer(target)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("无法打开", str(exc))

    # ==================================================================
    # 执行
    # ==================================================================
    def src_ext(self) -> str:
        if self.src_files:
            return ext_of(self.src_files[0])
        return ""

    def _build_jobs(self):
        tab = self.current_tab()
        if tab is None:
            return [], "没有可用的功能页"

        # 开工前重新探测：期间文件可能被替换过，或上次探测失败。
        # 这个结果会影响「是否需要重新编码」「有没有音轨」等自动判断。
        if self.src_files:
            if len(self.src_files) > 1:
                self.status_text.set(f"正在读取媒体信息…（共 {len(self.src_files)} 个文件）")
                self.update_idletasks()
            for path in self.src_files:
                self.get_info(path, refresh=True)
            self.info = self.info_cache.get(self.src_files[0])
            if self.info is None:
                self.log(f"警告：ffprobe 无法解析 {os.path.basename(self.src_files[0])}，"
                         "部分自动判断可能不准确", "warn")
            try:
                tab.on_src_changed()
            except Exception:
                pass

        error = tab.validate()
        if error:
            return None, error

        if tab.batch_exclusive:
            src = tab.src_override or (self.src_files[0] if self.src_files else None)
            if not src:
                return None, "请先选择源文件。"
            if tab.src_override:
                pattern = str(src)
                head = pattern.split("%")[0]
                folder = os.path.dirname(os.path.abspath(head)) or os.getcwd()
                stem = os.path.splitext(os.path.basename(head))[0] or "sequence"
                # 模板名常以 _ / - 结尾（img_%04d.jpg -> img_），去掉避免拼出 img__video.mp4
                stem = stem.rstrip("_-") or "sequence"
                custom_dir = self.out_path.get().strip()
                if self.out_mode.get() == "custom" and custom_dir and os.path.isdir(custom_dir):
                    folder = custom_dir
                dst = os.path.join(folder, f"{stem}{tab.output_suffix()}.{tab.output_ext()}")
            else:
                dst = self.resolve_output(src, tab)
            dst = tab.resolve_output(src, dst)
            if same_file(src, dst):
                return None, f"输出路径与源文件相同，会导致源文件被覆盖：\n{dst}"
            args = tab.build_cmd(src, dst)
            jobs = [Job(src, dst, args,
                        duration=tab.expected_duration(src) or 0.0,
                        total_frames=tab.expected_frames(src),
                        aux_files=tab.aux_files())]
            return jobs, None

        if not self.src_files:
            return None, "请先选择源文件。"

        jobs = []
        for src in self.src_files:
            dst = self.resolve_output(src, tab)
            dst = tab.resolve_output(src, dst)
            if same_file(src, dst):
                return None, f"输出路径与源文件相同，会导致源文件被覆盖：\n{dst}"
            args = tab.build_cmd(src, dst)
            jobs.append(Job(src, dst, args,
                            duration=tab.expected_duration(src) or 0.0,
                            total_frames=tab.expected_frames(src),
                            aux_files=tab.aux_files()))
        return jobs, None

    def on_start(self):
        if self._runner_busy():
            return
        if not self.ffmpeg_path:
            messagebox.showerror("未找到 ffmpeg", self.startup_error or "请先安装 ffmpeg 并加入 PATH。")
            return

        jobs, error = self._build_jobs()
        if error:
            messagebox.showwarning("无法开始", error)
            return
        if not jobs:
            return

        # 冲突检查
        dests = [os.path.normcase(os.path.abspath(j.dst)) for j in jobs]
        if len(set(dests)) != len(dests):
            messagebox.showwarning("输出冲突", "多个任务会写入同一个输出文件，请改用输出目录。")
            return
        for job in jobs:
            if os.path.exists(job.dst):
                # 未勾选覆盖时不能先删再跑：否则「不覆盖」选项形同虚设，
                # 用户已有的文件会被静默替换掉。
                if not self.overwrite.get():
                    messagebox.showerror(
                        "输出文件已存在",
                        f"{job.dst}\n\n同名文件已存在。勾选「覆盖已存在的同名文件」后重试，"
                        "或换一个输出路径。")
                    return
                # 勾选了覆盖也不预删除：任务中途失败时用户的原文件会跟着消失。
                # 只做一次写入探测，把「文件被占用」这种问题在开工前就说清楚。
                try:
                    with open(job.dst, "r+b"):
                        pass
                except OSError as exc:
                    messagebox.showerror("无法写入输出文件",
                                         f"{job.dst}\n\n{exc}\n\n"
                                         "该文件正被其他程序占用（或设为只读），"
                                         "请先关闭占用它的程序。")
                    return

        self.log_panel.write("─" * 60, "dim")
        self.log(f"开始处理，共 {len(jobs)} 个任务", "ok")
        self._last_output_dir = os.path.dirname(os.path.abspath(jobs[0].dst))

        self.btn_start.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self._reset_progress()
        if jobs[0].total_frames > 0:
            extra = f"（共 {len(jobs)} 个任务）" if len(jobs) > 1 else ""
            self.log(f"预计总帧数：{jobs[0].total_frames} 帧{extra}", "dim")
        elif jobs[0].duration > 0:
            self.log(f"预计输出时长：{format_time(jobs[0].duration)}", "dim")
        else:
            self.log("无法确定输出规模，进度条将以「处理中」动画显示", "warn")

        self.runner = JobRunner(
            jobs,
            self.ffmpeg_path,
            loglevel=self.log_level.get(),
            on_log=lambda line, kind="info": self._queue.put(("log", line, kind)),
            on_progress=lambda p: self._queue.put(("progress", p)),
            on_job_start=lambda i, job: self._queue.put(("job_start", i, job)),
            on_job_done=lambda i, job, ok, msg: self._queue.put(("job_done", i, job, ok, msg)),
            on_finished=lambda ok, msg: self._queue.put(("finished", ok, msg)),
            overwrite=self.overwrite.get(),
        )
        self.runner.start()

    def on_cancel(self):
        if self._runner_busy():
            self.runner.cancel()
            self.status_text.set("正在停止…")
            self.log("已请求停止，等待当前任务退出…", "warn")

    # ------------------------------------------------------------------
    def _drain_queue(self):
        if self._closing:
            return
        try:
            for _ in range(80):
                try:
                    event = self._queue.get_nowait()
                except queue.Empty:
                    break
                kind = event[0]
                if kind == "log":
                    self.log(event[1], event[2])
                elif kind == "probed":
                    self._apply_probe(event[1], event[2])
                elif kind == "progress":
                    self._apply_progress(event[1])
                elif kind == "job_start":
                    idx, job = event[1], event[2]
                    self.status_text.set(
                        f"[{idx + 1}/{self.runner.jobs.__len__()}] 正在处理 {os.path.basename(job.src)}")
                elif kind == "job_done":
                    job, ok, msg = event[2], event[3], event[4]
                    if ok:
                        size = human_size(os.path.getsize(job.dst)) if os.path.exists(job.dst) else "-"
                        self.log(f"✓ 完成：{os.path.basename(job.dst)}  ({size})", "ok")
                    else:
                        self.log(f"✗ 失败：{os.path.basename(job.src)} —— {msg}", "error")
                elif kind == "finished":
                    self._on_finished(event[1], event[2])
        except Exception:
            pass
        self._flush_log()
        self._drain_after = self.after(120, self._drain_queue)

    def _set_progress_determinate(self):
        try:
            if str(self.progress.cget("mode")) != "determinate":
                self.progress.stop()
                self.progress.configure(mode="determinate")
        except tk.TclError:
            pass

    def _set_progress_indeterminate(self):
        try:
            if str(self.progress.cget("mode")) != "indeterminate":
                self.progress.configure(mode="indeterminate")
                self.progress.start(55)
        except tk.TclError:
            pass

    def _reset_progress(self):
        try:
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)
        except tk.TclError:
            pass
        self.percent_text.set("0.0%")

    def _apply_progress(self, p):
        value = p.overall if p.job_total > 1 else p.percent
        if p.has_duration:
            self._set_progress_determinate()
            self.progress.configure(value=value)
            self.percent_text.set(f"{value:.1f}%")
        else:
            # 预期总时长未知（源文件探测失败等）时，改用滚动动画表示「正在处理」，
            # 而不是让进度条冻在 0% —— 看起来像卡死。
            self._set_progress_indeterminate()
            self.percent_text.set("处理中")

        parts = []
        if p.job_total > 1:
            parts.append(f"第 {p.job_index + 1}/{p.job_total} 个")
        if p.total_frames > 0:
            parts.append(f"帧 {p.frame_num}/{p.total_frames}")
        else:
            parts.append(f"已处理 {format_time(p.out_time, 1)}")
        parts.append(f"已用时 {format_time(p.elapsed, 0)}")
        if p.speed:
            parts.append(f"速度 {p.speed}")
        if p.fps:
            parts.append(f"{p.fps} fps")
        if p.size:
            parts.append(f"输出 {p.size}")
        self.status_text.set("  ·  ".join(parts))

    def _on_finished(self, ok, msg):
        # 只看当前页是否可执行：原来写的是 (current_tab() or src_files)，
        # 而 current_tab() 恒为真值，会把「信息」这类不可执行的页面也点亮开始按钮。
        tab = self.current_tab()
        runnable = bool(tab and tab.runnable and not self.startup_error)
        self.btn_start.configure(state="normal" if runnable else "disabled")
        self.btn_cancel.configure(state="disabled")
        self._reset_progress()
        if ok:
            self.progress.configure(value=100)
            self.percent_text.set("100%")
            self.log(f"✔ {msg}", "ok")
        else:
            # 批量任务现在是「失败也继续跑完」，只要有成功产物就用警告色而不是错误色
            results = getattr(self.runner, "results", None) or []
            partial = any(ok_one for _dst, ok_one, _m in results)
            self.log(f"■ {msg}", "warn" if partial else "error")
        self.status_text.set(msg)
        self._last_preview = ""
        self._flush_log()
        # 任务刚结束，立即把预览恢复成真实命令行，不必等下一轮轮询
        self._refresh_preview_text()

    def _cleanup_tabs(self):
        """清理各功能页产生的临时文件（拼接清单、水印文本等）。"""
        for tab in getattr(self, "tabs", []):
            try:
                tab.cleanup()
            except Exception:
                pass

    def destroy(self):
        # 先停掉定时回调，再清理临时文件，避免退出后 Tcl 报
        # 「invalid command name ..._drain_queue」
        self._closing = True
        for attr in ("_drain_after", "_preview_after"):
            aid = getattr(self, attr, None)
            if aid:
                try:
                    self.after_cancel(aid)
                except Exception:
                    pass
                setattr(self, attr, None)
        self._cleanup_tabs()
        try:
            super().destroy()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    def _on_close(self):
        # 无论出现什么异常，都必须能关掉窗口
        try:
            if self._runner_busy():
                if not messagebox.askyesno("正在处理",
                                           "还有任务正在执行，确定要退出吗？\n退出会中断当前任务。"):
                    return
                self.runner.cancel()
        except Exception:
            pass
        self.destroy()
