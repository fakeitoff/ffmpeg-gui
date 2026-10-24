# -*- coding: utf-8 -*-
"""操作分支内使用的小表单布局助手（各功能页共用）。"""
from __future__ import annotations

from tkinter import ttk

from ..widgets import scaled


class SubForm:
    """在一段区域内独立排版的两列表单：左标签、右控件。"""

    def __init__(self, parent, label_width: int = 13):
        self.parent = parent
        self.row = 0
        self.label_width = label_width
        parent.columnconfigure(1, weight=1)

    # -- 基础 -------------------------------------------------------------
    def field(self, label: str = "") -> ttk.Frame:
        row = self.row
        self.row += 1
        if label:
            ttk.Label(self.parent, text=label, style="Form.TLabel", width=self.label_width,
                      anchor="w").grid(row=row, column=0, sticky="w", pady=5, padx=(0, 10))
        holder = ttk.Frame(self.parent, style="Panel.TFrame")
        holder.grid(row=row, column=1, sticky="ew", pady=5)
        holder.columnconfigure(0, weight=1)
        return holder

    # -- 控件 -------------------------------------------------------------
    def entry(self, label, var, width=26):
        f = self.field(label)
        ttk.Entry(f, textvariable=var, width=width).grid(row=0, column=0, sticky="w")
        return f

    def field_hint(self, label, var, suffix="", hint="", width=10):
        f = self.field(label)
        ttk.Entry(f, textvariable=var, width=width).grid(row=0, column=0, sticky="w")
        text = " ".join(x for x in (suffix, hint) if x)
        if text:
            ttk.Label(f, text=text, style="PanelMuted.TLabel").grid(row=0, column=1, padx=(10, 0))
        return f

    def pair(self, label, var_a, suffix_a, var_b, values_b=None, combo_width=10):
        f = self.field(label)
        ttk.Entry(f, textvariable=var_a, width=8).grid(row=0, column=0, sticky="w")
        ttk.Label(f, text=suffix_a, style="PanelMuted.TLabel").grid(row=0, column=1, padx=(4, 14))
        if values_b is not None:
            ttk.Combobox(f, textvariable=var_b, values=list(values_b), width=combo_width,
                         state="readonly").grid(row=0, column=2, sticky="w")
        else:
            ttk.Entry(f, textvariable=var_b, width=8).grid(row=0, column=2, sticky="w")
        return f

    def file_row(self, label, var, picker, types=None, hint=""):
        f = self.field(label)
        ttk.Entry(f, textvariable=var).grid(row=0, column=0, sticky="ew")
        ttk.Button(f, text="浏览…", width=7, command=picker).grid(row=0, column=1, padx=(6, 0))
        f.columnconfigure(0, weight=1)
        if hint:
            ttk.Label(f, text=hint, style="PanelMuted.TLabel").grid(
                row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
        return f

    def combo(self, label, var, values, width=20, on_change=None):
        f = self.field(label)
        cb = ttk.Combobox(f, textvariable=var, values=list(values), width=width, state="readonly")
        cb.grid(row=0, column=0, sticky="w")
        if on_change:
            cb.bind("<<ComboboxSelected>>", lambda e: on_change())
        return f

    def check(self, label, var, text="", on_change=None):
        f = self.field(label)
        ttk.Checkbutton(f, text=text, variable=var, command=on_change).grid(
            row=0, column=0, sticky="w")
        return f

    def radio_row(self, label, var, options):
        """options: ``[(value, text), ...]``"""
        f = self.field(label)
        for i, (value, text) in enumerate(options):
            ttk.Radiobutton(f, text=text, value=value, variable=var).grid(
                row=0, column=i, sticky="w", padx=(0, 18))
        return f

    def note(self, text):
        row = self.row
        self.row += 1
        ttk.Label(self.parent, text=text, style="PanelMuted.TLabel",
                  wraplength=scaled(self.parent, 640),
                  justify="left").grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))
