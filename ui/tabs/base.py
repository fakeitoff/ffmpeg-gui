# -*- coding: utf-8 -*-
"""功能页基类。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..widgets import Form, ScrollFrame, scaled


class BuildError(Exception):
    """参数不合法，无法构建命令。"""


class BaseTab(ttk.Frame):
    """所有功能页的父类。

    子类需要实现 :meth:`build_cmd`，可选实现 :meth:`validate` 与
    :meth:`on_src_changed`。
    """

    name = "功能"
    hint = ""
    accept = "any"          # any / video / audio / image / sub
    default_ext = "mp4"
    suffix = "_out"
    needs_single_src = False
    runnable = True         # 是否能执行（信息页为 False）

    def __init__(self, master, app):
        super().__init__(master, style="Panel.TFrame")
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        outer = ScrollFrame(self)
        outer.grid(row=0, column=0, sticky="nsew")
        body = outer.inner
        body.columnconfigure(0, weight=1)

        header = ttk.Frame(body, style="Panel.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(8, 4), padx=16)
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=self.name, style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w")
        if self.hint:
            ttk.Label(body, text=self.hint, style="PanelMuted.TLabel",
                      wraplength=scaled(body, 820), justify="left").grid(
                row=1, column=0, sticky="w", padx=16, pady=(0, 6))

        self.form_holder = ttk.Frame(body, style="Panel.TFrame")
        self.form_holder.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 18))
        self.form_holder.columnconfigure(1, weight=1)
        self.form = Form(self.form_holder, label_width=13, pad=5)

        self.build()

    # -- 子类接口 ---------------------------------------------------------
    def build(self):
        """构建界面控件。"""
        raise NotImplementedError

    def build_cmd(self, src: str, dst: str) -> list[str]:
        """返回完整 ffmpeg 参数（须包含 ``-i src`` 与输出 ``dst``）。"""
        raise NotImplementedError

    def validate(self) -> str | None:
        """返回错误信息；None 表示通过。"""
        return None

    def on_src_changed(self):
        """源文件发生变化或探测完成后的回调。"""
        pass

    def output_ext(self) -> str:
        """当前设置对应的输出扩展名（影响自动命名）。"""
        return self.default_ext

    def output_suffix(self) -> str:
        return self.suffix

    @property
    def batch_exclusive(self) -> bool:
        """为 True 时整批文件只产生一个任务（如拼接、图片序列合片）。"""
        return False

    @property
    def src_override(self) -> str | None:
        """为 True 的 batch_exclusive 模式下，可指定自定义输入路径。"""
        return None

    def resolve_output(self, src: str, proposed: str) -> str:
        """允许功能页调整最终输出路径（如输出图片序列的 %03d 模板）。"""
        return proposed

    def aux_files(self) -> list[str]:
        """返回本次任务需要顺手清理的辅助文件（任务结束后由执行器删除）。"""
        return []

    def cleanup(self):
        """功能页退出 / 被销毁时清理自己产生的辅助文件。"""
        pass

    # -- 工具方法 ---------------------------------------------------------
    @property
    def info(self):
        return self.app.info

    def has_video(self) -> bool:
        return bool(self.app.info and self.app.info.has_video)

    def has_audio(self) -> bool:
        return bool(self.app.info and self.app.info.has_audio)

    def src_duration(self) -> float:
        return float(self.app.info.duration) if self.app.info else 0.0

    def expected_duration(self, src: str) -> float | None:
        """预估本次输出的时长（秒），用于进度条百分比；``None`` 表示未知。

        默认按「时长不变」处理（绝大多数转码 / 滤镜操作），并按**当前这个文件**
        取时长——批量处理时每个文件长度不同，不能统一用第一个文件的。
        拼接、合并等会改变时长的操作由对应页面覆写。
        """
        info = self.app.get_info(src)
        return float(info.duration) if info and info.duration else None

    def expected_frames(self, src: str) -> int:
        """预估本次输出的视频总帧数（用于按实际处理帧数算进度）；0 表示未知。

        默认等于源视频帧数（绝大多数转码 / 滤镜不改变帧数）。
        会改变帧数的操作（拼接、剪辑、改帧率等）由对应页面覆写。
        """
        info = self.app.get_info(src)
        return info.video_frames if info else 0

    def notify_output_changed(self):
        """当输出扩展名等发生变化时通知主窗口刷新命名。"""
        self.app.refresh_auto_output()

    @staticmethod
    def row(parent) -> ttk.Frame:
        f = ttk.Frame(parent, style="Panel.TFrame")
        f.columnconfigure(0, weight=1)
        return f
