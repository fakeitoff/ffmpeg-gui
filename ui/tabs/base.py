# -*- coding: utf-8 -*-
"""功能页基类。"""
from __future__ import annotations

from tkinter import ttk

from core import probe

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

    @property
    def src_is_remote(self) -> bool:
        """src_override 给的是在线地址（而非本地路径）时为 True。

        在线地址没有「源文件所在目录」，输出必须另找落点，
        主窗口据此决定命名与落盘位置。
        """
        return False

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

    def subtitle_codecs(self, *paths) -> list[str]:
        """按映射顺序返回这些文件里字幕流的编码名；探测不到的按无字幕处理。

        用于给 ``-c:s:<序号>`` 指定目标编码：序号必须与 ffmpeg 实际映射的
        字幕流顺序一致，所以这里严格按传入文件的顺序展开。
        """
        codecs: list[str] = []
        for path in paths:
            if not path:
                continue
            info = self.app.get_info(path)
            if info is None:
                continue
            codecs += [s.codec for s in info.streams if s.type == "subtitle"]
        return codecs

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
        会改变帧数的操作（剪辑、改帧率、变速、拼接等）必须覆写本方法，
        否则进度条会按源文件帧数去算，算出偏小的百分比并卡住。
        """
        info = self.app.get_info(src)
        return info.video_frames if info else 0

    # -- 帧数预估辅助 ------------------------------------------------------
    def src_fps(self, src: str) -> float:
        """源文件的视频帧率；0 表示未知。"""
        info = self.app.get_info(src)
        if info is None or info.video is None:
            return 0.0
        return float(info.video.fps or 0.0)

    def frames_from_duration(self, src: str, seconds: float | None) -> int:
        """按时长 × 源帧率估算帧数；时长或帧率未知时返回 0。

        适合「只改变时长、不改变帧率」的操作（如剪辑）。
        输出帧率与源帧率不同时（改帧率、变速），请自行传入输出帧率。
        """
        if not seconds or seconds <= 0:
            return 0
        fps = self.src_fps(src)
        if fps <= 0:
            return 0
        return max(1, int(round(seconds * fps)))

    @staticmethod
    def frames_from_fps(seconds: float | None, fps) -> int:
        """按「输出时长 × 输出帧率」估算帧数；任一未知返回 0。"""
        if not seconds or seconds <= 0:
            return 0
        try:
            f = float(str(fps).strip())
        except (TypeError, ValueError):
            return 0
        if f <= 0:
            return 0
        return max(1, int(round(seconds * f)))

    @staticmethod
    def _positive_float(value) -> float:
        """把界面输入解析为正数；失败或非正返回 0。"""
        try:
            f = float(str(value).strip())
        except (TypeError, ValueError):
            return 0.0
        return f if f > 0 else 0.0

    def amix_args(self, inputs: int = 2, duration: str = "first") -> str:
        """拼 amix 的参数串。

        amix 默认会把每条输入按比例衰减（两条轨各占一半音量），混完背景音乐后
        原声明显变轻。新版 ffmpeg 有 ``normalize=0`` 可以关掉这个自动衰减，
        老版本写了这个选项会直接报错，所以按能力判断后再拼进命令。
        """
        base = f"amix=inputs={inputs}:duration={duration}:dropout_transition=2"
        if probe.filter_has_option(self.app.ffmpeg_path, "amix", "normalize"):
            base += ":normalize=0"
        return base

    def notify_output_changed(self):
        """当输出扩展名等发生变化时通知主窗口刷新命名。"""
        self.app.refresh_auto_output()

    @staticmethod
    def row(parent) -> ttk.Frame:
        f = ttk.Frame(parent, style="Panel.TFrame")
        f.columnconfigure(0, weight=1)
        return f
