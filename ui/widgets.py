# -*- coding: utf-8 -*-
"""可复用界面组件。"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, ttk

from . import theme


def scaled(widget, px: int) -> int:
    """把 96 DPI 下的设计像素换算为当前屏幕的实际像素（用于 wraplength 等）。"""
    try:
        return int(px * widget.winfo_fpixels("1i") / 96.0)
    except Exception:
        return px


class Form:
    """两列表单布局助手：左侧标签、右侧控件容器。"""

    def __init__(self, parent: tk.Misc, label_width: int = 12, pad: int = 5):
        self.parent = parent
        self.label_width = label_width
        self.pad = pad
        self.row = 0
        parent.columnconfigure(1, weight=1)

    # -- 基础 -------------------------------------------------------------
    def _label(self, text: str, row: int, style: str = "Form.TLabel"):
        lbl = ttk.Label(self.parent, text=text, style=style, width=self.label_width, anchor="w")
        lbl.grid(row=row, column=0, sticky="w", pady=self.pad, padx=(0, 10))
        return lbl

    def field(self, label: str = "") -> ttk.Frame:
        """新增一行，返回右侧容器。"""
        row = self.row
        self.row += 1
        if label:
            self._label(label, row)
        f = ttk.Frame(self.parent, style="Panel.TFrame")
        f.grid(row=row, column=1, sticky="ew", pady=self.pad)
        f.columnconfigure(0, weight=1)
        return f

    def full_row(self, pady=0, stretch: bool = False) -> ttk.Frame:
        """占用整整一行（横跨两列），返回容器；用于放自定义控件。

        ``stretch=True`` 时该行会跟随窗口纵向拉伸。
        统一走这里分配行号，避免手工 +1 导致控件叠在同一格里。
        """
        row = self.row
        self.row += 1
        holder = ttk.Frame(self.parent, style="Panel.TFrame")
        holder.grid(row=row, column=0, columnspan=2, sticky="nsew", pady=pady)
        holder.columnconfigure(0, weight=1)
        if stretch:
            self.parent.rowconfigure(row, weight=1)
        return holder

    def section(self, title: str):
        row = self.row
        self.row += 1
        holder = ttk.Frame(self.parent, style="Panel.TFrame")
        holder.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(14, 6))
        holder.columnconfigure(0, weight=1)
        ttk.Label(holder, text=title, style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Separator(holder, orient="horizontal").grid(row=1, column=0, sticky="ew", pady=(4, 0))
        return holder

    def note(self, text: str):
        row = self.row
        self.row += 1
        ttk.Label(self.parent, text=text, style="PanelMuted.TLabel",
                  wraplength=scaled(self.parent, 680), justify="left").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))

    # -- 控件 -------------------------------------------------------------
    def entry(self, label: str, var: tk.StringVar, width: int = 24,
              browse=None, browse_text: str = "浏览…", extra=None, show=None):
        f = self.field(label)
        ent = ttk.Entry(f, textvariable=var, width=width, show=show)
        ent.grid(row=0, column=0, sticky="ew")
        col = 1
        if browse:
            ttk.Button(f, text=browse_text, command=browse, width=7).grid(row=0, column=col, padx=(6, 0))
            col += 1
        if extra:
            extra(f, col)
        return ent

    def combo(self, label: str, var: tk.StringVar, values, width: int = 22,
              readonly: bool = True, on_change=None, extra=None):
        f = self.field(label)
        cb = ttk.Combobox(f, textvariable=var, values=list(values), width=width,
                          state="readonly" if readonly else "normal")
        cb.grid(row=0, column=0, sticky="w")
        if on_change:
            cb.bind("<<ComboboxSelected>>", lambda e: on_change())
        if extra:
            extra(f, 1)
        return cb

    def spin(self, label: str, var: tk.StringVar, from_=0, to=1000, width: int = 8,
             increment: int = 1, on_change=None, suffix_label: str = ""):
        f = self.field(label)
        sp = ttk.Spinbox(f, textvariable=var, from_=from_, to=to, width=width,
                         increment=increment, command=on_change)
        sp.grid(row=0, column=0, sticky="w")
        sp.bind("<KeyRelease>", lambda e: on_change() if on_change else None)
        if suffix_label:
            ttk.Label(f, text=suffix_label, style="PanelMuted.TLabel").grid(row=0, column=1, padx=(6, 0))
        return sp

    def check(self, label: str, var: tk.BooleanVar, text: str = "", on_change=None):
        f = self.field(label)
        cb = ttk.Checkbutton(f, text=text, variable=var, command=on_change)
        cb.grid(row=0, column=0, sticky="w")
        return cb

    def scale(self, label: str, var: tk.IntVar, from_=0, to=51,
              on_change=None, width: int = 300, show_value: bool = True, unit: str = "",
              extra=None):
        f = self.field(label)
        holder = ttk.Frame(f, style="Panel.TFrame")
        holder.grid(row=0, column=0, sticky="ew")
        holder.columnconfigure(0, weight=1)
        s = ttk.Scale(holder, from_=from_, to=to, variable=var, orient="horizontal",
                      command=lambda v: (on_change() if on_change else None))
        s.grid(row=0, column=0, sticky="ew")
        col = 1
        if show_value:
            val = ttk.Label(holder, textvariable=var, style="Form.TLabel", width=4, anchor="e")
            val.grid(row=0, column=col, padx=(8, 0))
            col += 1
            if unit:
                ttk.Label(holder, text=unit, style="PanelMuted.TLabel").grid(
                    row=0, column=col, padx=(2, 0))
                col += 1
        if extra:
            extra(holder, col)
        return s

    def fscale(self, label: str, var: tk.DoubleVar, from_, to, on_change=None,
               width: int = 300, fmt: str = "{:.2f}", unit: str = "", extra=None):
        """浮点滑块（用于亮度/对比度等连续参数）。"""
        f = self.field(label)
        holder = ttk.Frame(f, style="Panel.TFrame")
        holder.grid(row=0, column=0, sticky="ew")
        holder.columnconfigure(0, weight=1)
        s = ttk.Scale(holder, from_=from_, to=to, variable=var, orient="horizontal",
                      command=lambda v: (on_change() if on_change else None))
        s.grid(row=0, column=0, sticky="ew")

        def show(*_a):
            try:
                lbl.configure(text=fmt.format(float(var.get())))
            except (tk.TclError, ValueError):
                pass

        lbl = ttk.Label(holder, text=fmt.format(float(var.get())), style="Form.TLabel",
                        width=7, anchor="e")
        lbl.grid(row=0, column=1, padx=(8, 0))
        var.trace_add("write", show)
        col = 2
        if unit:
            ttk.Label(holder, text=unit, style="PanelMuted.TLabel").grid(row=0, column=col, padx=(2, 0))
            col += 1
        if extra:
            extra(holder, col)
        return s

    def radios(self, label: str, var: tk.StringVar, options, on_change=None):
        """options: ``[(value, text), ...]``"""
        f = self.field(label)
        holder = ttk.Frame(f, style="Panel.TFrame")
        holder.grid(row=0, column=0, sticky="w")
        for i, opt in enumerate(options):
            value, text = opt[0], opt[1]
            rb = ttk.Radiobutton(holder, text=text, value=value, variable=var, command=on_change)
            rb.grid(row=0, column=i, padx=(0, 14), sticky="w")
        return holder

    def time_row(self, label: str, var: tk.StringVar, hint: str = "", on_change=None):
        f = self.field(label)
        ent = ttk.Entry(f, textvariable=var, width=14)
        ent.grid(row=0, column=0, sticky="w")
        ent.bind("<KeyRelease>", lambda e: on_change() if on_change else None)
        if hint:
            ttk.Label(f, text=hint, style="PanelMuted.TLabel").grid(row=0, column=1, padx=(8, 0))
        return ent


# --------------------------------------------------------------------------
# 日志面板
# --------------------------------------------------------------------------
class LogPanel(ttk.Frame):
    """带颜色标记、右键菜单与自动滚动的日志输出区。"""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.text = tk.Text(self, height=8, wrap="none", bg=theme.LOG_BG, fg=theme.TEXT,
                            insertbackground=theme.TEXT, relief="flat", borderwidth=0,
                            font=(theme.MONO, 9), padx=8, pady=6, state="normal")
        self.text.grid(row=0, column=0, sticky="nsew")

        vsb = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        hsb = ttk.Scrollbar(self, orient="horizontal", command=self.text.xview)
        hsb.grid(row=1, column=0, sticky="ew")
        self.text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.text.tag_configure("info", foreground="#3b4148")
        self.text.tag_configure("cmd", foreground=theme.ACCENT)
        self.text.tag_configure("warn", foreground=theme.WARN)
        self.text.tag_configure("error", foreground=theme.ERR)
        self.text.tag_configure("ok", foreground=theme.OK)
        self.text.tag_configure("dim", foreground=theme.MUTED)

        self._menu = tk.Menu(self, tearoff=0)
        self._menu.add_command(label="复制选中内容", command=self._copy)
        self._menu.add_command(label="全选", command=lambda: self.text.tag_add("sel", "1.0", "end"))
        self._menu.add_separator()
        self._menu.add_command(label="清空", command=self.clear)
        self._menu.add_command(label="另存为日志文件…", command=self.save_as)
        self.text.bind("<Button-3>", self._popup)

    def _popup(self, event):
        try:
            self._menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._menu.grab_release()

    def _copy(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self.text.get("sel.first", "sel.last"))
        except tk.TclError:
            pass

    # 超过这个行数就丢弃最旧的，避免长时间任务把 Text 撑到几万行拖慢重绘
    MAX_LINES = 4000

    def write(self, line: str, kind: str = "info"):
        self.write_many([(line, kind)])

    def write_many(self, items):
        """批量写入日志。合并连续同类型标签后一次性插入，减少 Tcl 调用。"""
        if not items:
            return
        buf: list[str] = []
        cur = "info"
        for line, kind in items:
            k = kind or "info"
            if k != cur and buf:
                self.text.insert("end", "\n".join(buf) + "\n", cur)
                buf = []
            cur = k
            buf.append(str(line))
        if buf:
            self.text.insert("end", "\n".join(buf) + "\n", cur)
        self._trim()
        self.text.see("end")

    def _trim(self):
        try:
            total = int(self.text.index("end-1c").split(".")[0])
            if total > self.MAX_LINES:
                self.text.delete("1.0", f"{total - self.MAX_LINES}.0")
        except (tk.TclError, ValueError):
            pass

    def clear(self):
        self.text.delete("1.0", "end")

    def save_as(self):
        path = filedialog.asksaveasfilename(
            title="保存日志", defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialfile="ffmpeg-gui.log")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.text.get("1.0", "end"))


# --------------------------------------------------------------------------
# 路径输入行
# --------------------------------------------------------------------------
def ask_open_files(parent, patterns, multiple=True, initialdir=None):
    """封装多选文件对话框。patterns 形如 [("视频文件", "*.mp4 *.mkv")]。"""
    filetypes = list(patterns) + [("所有文件", "*.*")]
    if multiple:
        return list(filedialog.askopenfilenames(parent=parent, title="选择文件",
                                                filetypes=filetypes, initialdir=initialdir))
    p = filedialog.askopenfilename(parent=parent, title="选择文件",
                                   filetypes=filetypes, initialdir=initialdir)
    return [p] if p else []


VIDEO_TYPES = [("视频文件", "*.mp4 *.mkv *.mov *.avi *.flv *.wmv *.webm *.ts *.m4v *.mpg *.mpeg *.3gp *.rmvb *.vob *.ogv"),
               ("m3u8 播放列表", "*.m3u8 *.m3u"),
               ("音频文件", "*.mp3 *.aac *.wav *.flac *.ogg *.opus *.m4a *.wma *.ac3 *.ape")]
AUDIO_TYPES = [("音频文件", "*.mp3 *.aac *.wav *.flac *.ogg *.opus *.m4a *.wma *.ac3 *.ape"),
               ("视频文件", "*.mp4 *.mkv *.mov *.avi *.flv *.wmv *.webm *.ts")]
MEDIA_TYPES = [("媒体文件", "*.mp4 *.mkv *.mov *.avi *.flv *.wmv *.webm *.ts *.m4v *.m3u8 *.mp3 *.aac *.wav *.flac *.ogg *.opus *.m4a"),
               ("m3u8 播放列表", "*.m3u8 *.m3u"),
               ("视频文件", "*.mp4 *.mkv *.mov *.avi *.flv *.wmv *.webm *.ts *.m4v"),
               ("音频文件", "*.mp3 *.aac *.wav *.flac *.ogg *.opus *.m4a *.wma"),
               ("图片文件", "*.jpg *.jpeg *.png *.bmp *.webp *.gif *.tif")]
IMAGE_TYPES = [("图片文件", "*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff"),
               ("所有文件", "*.*")]
SUB_TYPES = [("字幕文件", "*.srt *.ass *.ssa *.vtt *.sub"), ("所有文件", "*.*")]


def filetypes_for(accept: str):
    return {
        "video": VIDEO_TYPES,
        "audio": AUDIO_TYPES,
        "image": IMAGE_TYPES,
        "sub": SUB_TYPES,
        "any": MEDIA_TYPES,
    }.get(accept, MEDIA_TYPES)


def path_label(path: str, max_len: int = 60) -> str:
    if not path:
        return ""
    name = os.path.basename(path)
    return name if len(name) <= max_len else name[: max_len - 1] + "…"


class FileListBox(ttk.Frame):
    """带「添加 / 移除 / 排序 / 清空」的多文件列表，用于需要多个输入文件的场景。"""

    def __init__(self, master, types=None, title="选择文件", height=4,
                 multiple=True, on_change=None):
        super().__init__(master, style="Panel.TFrame")
        self.types = types or MEDIA_TYPES
        self.title = title
        self.multiple = multiple
        self.on_change = on_change
        self._files: list[str] = []
        self.columnconfigure(0, weight=1)

        self.listbox = tk.Listbox(self, height=height, selectmode="extended",
                                  bg="#ffffff", fg=theme.TEXT, relief="solid", borderwidth=1,
                                  font=(theme.FONT, 9), activestyle="none",
                                  selectbackground="#dbe6fd", selectforeground=theme.TEXT,
                                  highlightthickness=0)
        self.listbox.grid(row=0, column=0, sticky="ew")
        sb = ttk.Scrollbar(self, orient="vertical", command=self.listbox.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=sb.set)

        btns = ttk.Frame(self, style="Panel.TFrame")
        btns.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Button(btns, text="添加…", width=8, command=self.pick).pack(side="left", padx=(0, 4))
        ttk.Button(btns, text="移除选中", width=10, command=self.remove_selected).pack(
            side="left", padx=(0, 4))
        ttk.Button(btns, text="清空", width=7, command=self.clear).pack(side="left", padx=(0, 4))
        ttk.Button(btns, text="↑", width=3, command=self.move_up).pack(side="left", padx=(0, 4))
        ttk.Button(btns, text="↓", width=3, command=self.move_down).pack(side="left")

    # -- 数据 -------------------------------------------------------------
    def files(self) -> list[str]:
        return list(self._files)

    def set_files(self, paths):
        self._files = [os.path.abspath(p) for p in paths if p]
        self._refresh()

    def add(self, paths):
        for p in paths:
            p = os.path.abspath(p)
            if p not in self._files:
                self._files.append(p)
        self._refresh()

    def pick(self):
        got = ask_open_files(self, self.types, multiple=self.multiple)
        if got:
            self.add(got)

    def remove_selected(self):
        for i in sorted(self.listbox.curselection(), reverse=True):
            if 0 <= i < len(self._files):
                self._files.pop(i)
        self._refresh()

    def clear(self):
        self._files.clear()
        self._refresh()

    def move_up(self):
        self._move_selected(-1)

    def move_down(self):
        self._move_selected(1)

    def _move_selected(self, delta: int):
        """整段移动且保持段内顺序（逐个交换会让相邻选中项互相越位）。"""
        sel = list(self.listbox.curselection())
        if not sel:
            return
        if min(sel) + delta < 0 or max(sel) + delta >= len(self._files):
            return
        order = sel if delta < 0 else list(reversed(sel))
        moved = set()
        for i in order:
            j = i + delta
            self._files[i], self._files[j] = self._files[j], self._files[i]
            moved.add(j)
        self._refresh()
        for i in sorted(moved):
            self.listbox.selection_set(i)

    def _refresh(self):
        self.listbox.delete(0, "end")
        for path in self._files:
            self.listbox.insert("end", path)
        if self.on_change:
            self.on_change()


class ScrollFrame(ttk.Frame):
    """带滚动条的容器。

    内容比可视区窄时横向撑满窗口；一旦某个页面的控件排得太宽
    （小屏幕或高缩放比下很容易发生），自动出现横向滚动条兜底，
    不会出现「右边被切掉、看不到也够不着」的情况。
    """

    def __init__(self, master, bg: str = theme.PANEL):
        super().__init__(master, style="Panel.TFrame")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, borderwidth=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.hsb = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vsb.set, xscrollcommand=self.hsb.set)

        self.inner = ttk.Frame(self.canvas, style="Panel.TFrame")
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.canvas.bind("<Enter>", lambda e: self._wheel(True))
        self.canvas.bind("<Leave>", lambda e: self._wheel(False))

    def _on_inner(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._sync_hbar()

    def _sync_hbar(self):
        """只有在内容确实超出可视宽度时才显示横向滚动条。"""
        try:
            need = self.inner.winfo_reqwidth() > self.canvas.winfo_width() + 1
            if need and not self.hsb.winfo_ismapped():
                self.hsb.grid(row=1, column=0, sticky="ew")
            elif not need and self.hsb.winfo_ismapped():
                self.hsb.grid_remove()
        except tk.TclError:
            pass

    def _on_canvas(self, event):
        # 内容自然宽度大于可视区时不要压窄它（否则右侧会被裁掉），
        # 保持原宽并交给横向滚动条；否则横向撑满窗口。
        try:
            need = self.inner.winfo_reqwidth()
            want = max(event.width, need)
            if getattr(self, "_last_win_w", None) != want:
                self._last_win_w = want
                self.canvas.itemconfigure(self._win, width=want)
        except tk.TclError:
            return
        self._sync_hbar()

    def _wheel(self, enabled: bool):
        if enabled:
            self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
            self.canvas.bind_all("<Button-4>", self._on_mousewheel)
            self.canvas.bind_all("<Button-5>", self._on_mousewheel)
        else:
            self.canvas.unbind_all("<MouseWheel>")
            self.canvas.unbind_all("<Button-4>")
            self.canvas.unbind_all("<Button-5>")

    def _on_mousewheel(self, event):
        if self.inner.winfo_reqheight() <= self.canvas.winfo_height():
            return
        if getattr(event, "num", None) == 4:
            delta = 1
        elif getattr(event, "num", None) == 5:
            delta = -1
        else:
            delta = int(-event.delta / 120)
        self.canvas.yview_scroll(delta, "units")

