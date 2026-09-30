# -*- coding: utf-8 -*-
"""浅色主题与 ttk 样式定义。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

# 调色板（浅色主题）
BG = "#f3f4f6"        # 窗口底色
PANEL = "#ffffff"     # 卡片 / 面板
SUB = "#eef0f3"       # 次级面板
BORDER = "#d8dbe0"    # 描边
TEXT = "#1f2329"      # 主文本
MUTED = "#6b7280"     # 次要文本
ACCENT = "#2563eb"    # 主色
ACCENT_HOVER = "#1d4ed8"
OK = "#15803d"
WARN = "#b45309"
ERR = "#b91c1c"
LOG_BG = "#fbfbfc"

FONT = "Microsoft YaHei UI"
MONO = "Consolas"


def setup_theme(root: tk.Tk):
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    def base_font(size=10, bold=False):
        return (FONT, size, "bold") if bold else (FONT, size)

    root.configure(bg=BG)
    style.configure(".", background=BG, foreground=TEXT, font=base_font(10))
    style.configure("TFrame", background=BG)
    style.configure("Panel.TFrame", background=PANEL, relief="flat")
    style.configure("Sub.TFrame", background=SUB)
    style.configure("Card.TFrame", background=PANEL, relief="solid", borderwidth=1)

    style.configure("TLabel", background=BG, foreground=TEXT, font=base_font(10))
    style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
    style.configure("Sub.TLabel", background=SUB, foreground=TEXT)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=base_font(9))
    style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED, font=base_font(9))
    style.configure("Form.TLabel", background=PANEL, foreground=TEXT, font=base_font(10))
    style.configure("Section.TLabel", background=PANEL, foreground=ACCENT, font=base_font(11, True))
    style.configure("Title.TLabel", background=BG, foreground=TEXT, font=base_font(13, True))
    style.configure("PanelTitle.TLabel", background=PANEL, foreground=TEXT, font=base_font(13, True))
    style.configure("Hint.TLabel", background=BG, foreground=MUTED, font=base_font(9))

    style.configure("TLabelframe", background=PANEL, bordercolor=BORDER, relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=PANEL, foreground=ACCENT, font=base_font(10, True))

    style.configure("TButton", background=SUB, foreground=TEXT, font=base_font(10),
                    borderwidth=1, relief="flat", padding=(10, 5), focusthickness=0)
    style.map("TButton",
              background=[("pressed", "#dfe3e8"), ("active", "#e4e7eb")],
              foreground=[("disabled", "#a0a4aa")])

    style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", font=base_font(10, True),
                    padding=(18, 6), borderwidth=0)
    style.map("Accent.TButton",
              background=[("pressed", ACCENT_HOVER), ("active", ACCENT_HOVER), ("disabled", "#9db4e8")],
              foreground=[("disabled", "#eef2ff")])

    style.configure("Danger.TButton", background="#fee2e2", foreground=ERR, font=base_font(10),
                    padding=(14, 6), borderwidth=1)
    style.map("Danger.TButton", background=[("pressed", "#fecaca"), ("active", "#fecaca")])

    style.configure("Ghost.TButton", background=PANEL, foreground=MUTED, borderwidth=0, padding=(6, 2))
    style.map("Ghost.TButton", background=[("active", SUB)], foreground=[("active", ACCENT)])

    style.configure("TEntry", fieldbackground="#ffffff", foreground=TEXT, bordercolor=BORDER,
                    insertcolor=TEXT, padding=(6, 4), relief="flat")
    style.map("TEntry", bordercolor=[("focus", ACCENT)])

    style.configure("TCombobox", fieldbackground="#ffffff", background=SUB, foreground=TEXT,
                    bordercolor=BORDER, arrowcolor=MUTED, padding=(6, 3), relief="flat")
    style.map("TCombobox",
              fieldbackground=[("readonly", "#ffffff")],
              bordercolor=[("focus", ACCENT)])

    style.configure("TSpinbox", fieldbackground="#ffffff", foreground=TEXT, bordercolor=BORDER,
                    arrowcolor=MUTED, padding=(4, 3))
    style.map("TSpinbox", bordercolor=[("focus", ACCENT)])

    style.configure("TCheckbutton", background=PANEL, foreground=TEXT, font=base_font(10), focusthickness=0)
    style.map("TCheckbutton", background=[("active", PANEL)], foreground=[("disabled", "#a0a4aa")])
    style.configure("Bg.TCheckbutton", background=BG, foreground=TEXT)
    style.map("Bg.TCheckbutton", background=[("active", BG)])

    style.configure("TRadiobutton", background=PANEL, foreground=TEXT, font=base_font(10), focusthickness=0)
    style.map("TRadiobutton", background=[("active", PANEL)])
    style.configure("Bg.TRadiobutton", background=BG, foreground=TEXT)
    style.map("Bg.TRadiobutton", background=[("active", BG)])

    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(6, 6, 6, 0))
    style.configure("TNotebook.Tab", background=SUB, foreground=MUTED, padding=(16, 8),
                    font=base_font(10), borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", PANEL), ("active", "#e4e7eb")],
              foreground=[("selected", ACCENT), ("active", TEXT)],
              font=[("selected", base_font(10, True))])

    style.configure("Thin.Horizontal.TProgressbar", background=ACCENT, troughcolor="#e3e6ea",
                    bordercolor="#e3e6ea", lightcolor=ACCENT, darkcolor=ACCENT, thickness=10)
    style.configure("TScale", background=PANEL, troughcolor="#e3e6ea")
    style.configure("TSeparator", background=BORDER)
    style.configure("Vertical.TScrollbar", background=SUB, troughcolor=BG, bordercolor=BG,
                    arrowcolor=MUTED, relief="flat")
    style.configure("Horizontal.TScrollbar", background=SUB, troughcolor=BG, bordercolor=BG,
                    arrowcolor=MUTED, relief="flat")
    return style
