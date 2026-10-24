# -*- coding: utf-8 -*-
"""截图 / 缩略图 / 预览页。"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk

from core import builder
from core.util import format_time, parse_time
from .base import BaseTab
from .subform import SubForm as _SubForm

MODES = [
    ("frame", "单张截图（指定时间点抽一帧）"),
    ("frames", "批量截图（按间隔抽取多张）"),
    ("tile", "缩略图拼图（一张网格总览图）"),
    ("gif", "预览动图（导出 GIF 片段）"),
    ("seq", "图片序列合成视频（把文件夹里的图片做成视频）"),
]
MODE_KEY = {label: key for key, label in MODES}
MODE_LABEL = {key: label for key, label in MODES}

IMG_FORMATS = ["jpg", "png", "webp", "bmp"]
SCALES = ["原始尺寸", "1920", "1280", "854", "640", "480"]


class CaptureTab(BaseTab):
    name = "截图 / 预览"
    hint = ("抽取画面帧、生成缩略图网格、导出预览动图，"
            "或者把一整个文件夹的图片按序号合成视频。")
    accept = "video"
    suffix = "_frame"

    # ------------------------------------------------------------------
    def build(self):
        f = self.form
        self.mode = tk.StringVar(value=MODE_LABEL["frame"])

        self.time = tk.StringVar(value="00:00:05")
        self.img_fmt = tk.StringVar(value="jpg")
        self.quality = tk.StringVar(value="2")
        self.scale = tk.StringVar(value=SCALES[0])

        self.interval = tk.StringVar(value="10")
        self.max_count = tk.StringVar(value="0")

        self.tile_cols = tk.StringVar(value="4")
        self.tile_rows = tk.StringVar(value="4")
        self.tile_width = tk.StringVar(value="320")

        self.gif_start = tk.StringVar(value="0")
        self.gif_dur = tk.StringVar(value="5")
        self.gif_fps = tk.StringVar(value="12")
        self.gif_width = tk.StringVar(value="480")

        self.seq_pattern = tk.StringVar(value="")
        self.seq_fps = tk.StringVar(value="25")

        f.combo("模式", self.mode, [label for _k, label in MODES], width=46,
                on_change=self._on_mode)

        self.box = ttk.Frame(self.form_holder, style="Panel.TFrame")
        self.box.grid(row=f.row, column=0, columnspan=2, sticky="ew")
        self.box.columnconfigure(1, weight=1)
        f.row += 1
        self._build_boxes()
        self._on_mode()

    # ------------------------------------------------------------------
    def _new_box(self):
        box = ttk.Frame(self.box, style="Panel.TFrame")
        box.grid(row=0, column=1, sticky="ew")
        box.columnconfigure(1, weight=1)
        return box

    def _build_boxes(self):
        # 单张截图
        self.b_frame = self._new_box()
        g = _SubForm(self.b_frame)
        g.field_hint("截图时间", self.time, "", "格式 00:00:05 或 5.5")
        g.combo("图片格式", self.img_fmt, IMG_FORMATS, width=10)
        g.field_hint("质量", self.quality, "", "jpg 用 2~5（越小越清晰），png 无效")
        g.combo("缩放宽度", self.scale, SCALES, width=12)

        # 批量截图
        self.b_frames = self._new_box()
        g = _SubForm(self.b_frames)
        g.field_hint("抽取间隔", self.interval, "秒", "每隔多少秒抽一帧")
        g.field_hint("最大张数", self.max_count, "张", "0 表示不限制")
        g.combo("图片格式", self.img_fmt, IMG_FORMATS, width=10)
        g.combo("缩放宽度", self.scale, SCALES, width=12)
        g.note("输出文件会命名为 <原文件名>_0001.jpg、_0002.jpg …… 与源文件放在同一目录。")

        # 缩略图拼图
        self.b_tile = self._new_box()
        g = _SubForm(self.b_tile)
        g.pair("网格", self.tile_cols, "列 ×", self.tile_rows, None)
        g.field_hint("抽取间隔", self.interval, "秒", "每个格子间隔多少秒")
        g.field_hint("单格宽度", self.tile_width, "px", "")
        g.note("共需 列×行 个画面，即覆盖 列×行×间隔 秒的视频内容。")

        # 预览动图
        self.b_gif = self._new_box()
        g = _SubForm(self.b_gif)
        g.field_hint("起始时间", self.gif_start, "", "00:00:00 或 0")
        g.field_hint("持续时长", self.gif_dur, "秒", "")
        g.field_hint("帧率", self.gif_fps, "fps", "10 ~ 15 比较合适")
        g.field_hint("宽度", self.gif_width, "px", "高度按比例自动")

        # 图片序列合成视频
        self.b_seq = self._new_box()
        g = _SubForm(self.b_seq)
        row = g.field("图片文件夹")
        self.seq_dir_var = tk.StringVar(value="")
        ttk.Entry(row, textvariable=self.seq_dir_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(row, text="选择…", width=7, command=self._pick_dir).grid(row=0, column=1, padx=(6, 0))
        g.field_hint("图片模板", self.seq_pattern, "", "%04d 会自动替换为 0001、0002 …")
        g.field_hint("帧率", self.seq_fps, "fps", "决定视频时长与流畅度")
        g.note("示例：C:/photos/img_%04d.jpg 表示 img_0001.jpg、img_0002.jpg …… 依次读入。")

        self._boxes = {
            "frame": self.b_frame,
            "frames": self.b_frames,
            "tile": self.b_tile,
            "gif": self.b_gif,
            "seq": self.b_seq,
        }

    def _mode_key(self) -> str:
        return MODE_KEY.get(self.mode.get(), "frame")

    def _on_mode(self):
        for box in self._boxes.values():
            box.grid_remove()
        self._boxes[self._mode_key()].grid()
        self.notify_output_changed()

    def _pick_dir(self):
        from tkinter import filedialog

        d = filedialog.askdirectory(title="选择图片所在文件夹")
        if d:
            self.seq_dir_var.set(d)
            if not self.seq_pattern.get().strip():
                self.seq_pattern.set(os.path.join(d.replace("\\", "/"), "img_%04d.jpg"))

    # ------------------------------------------------------------------
    def output_ext(self) -> str:
        key = self._mode_key()
        if key == "gif":
            return "gif"
        if key == "seq":
            return "mp4"
        if key == "tile":
            return "jpg"
        return self.img_fmt.get()

    def output_suffix(self) -> str:
        return {"frame": "_frame", "frames": "_shot", "tile": "_tile",
                "gif": "_preview", "seq": "_video"}.get(self._mode_key(), "_frame")

    @property
    def batch_exclusive(self) -> bool:
        return self._mode_key() == "seq"

    @property
    def src_override(self) -> str | None:
        if self._mode_key() == "seq":
            return self.seq_pattern.get().strip()
        return None

    def resolve_output(self, src: str, proposed: str) -> str:
        if self._mode_key() == "frames":
            ext = self.img_fmt.get()
            base = os.path.splitext(proposed)[0]
            return f"{base}_%04d.{ext}"
        return proposed

    def validate(self):
        key = self._mode_key()
        if key == "seq":
            pattern = self.seq_pattern.get().strip()
            if not pattern:
                return "请选择图片文件夹或填写图片模板（如 img_%04d.jpg）。"
            return None
        if key == "frame":
            try:
                t = parse_time(self.time.get())
            except ValueError as exc:
                return str(exc)
            # 超出结尾时 ffmpeg 一帧都取不到，却照样建出 0 字节的图片，
            # 用户只看到「输出文件未生成或为空」，根本不知道是时间填错了。
            total = self.src_duration()
            if t is not None and total and t >= total:
                return (f"截图时间超出了视频长度：视频只有 {format_time(total, 1)}，"
                        f"而你要的是 {format_time(t, 1)}。")
            return None
        if key == "tile":
            cols = rows = 0
            for name, var in (("列数", self.tile_cols), ("行数", self.tile_rows)):
                try:
                    value = int(var.get())
                except ValueError:
                    return f"{name}必须是大于 0 的整数。"
                if value < 1:
                    return f"{name}必须是大于 0 的整数。"
                if name == "列数":
                    cols = value
                else:
                    rows = value
            try:
                interval = float(self.interval.get())
            except ValueError:
                interval = 10.0
            if interval <= 0:
                return "抽取间隔必须大于 0。"
            # tile 要凑满 列×行 帧才吐出一张图；素材不够时 ffmpeg 直接报
            # 「Could not open encoder before EOF」，磁盘上什么都不留。
            total = self.src_duration()
            need = cols * rows * interval
            if total and need > total:
                return (f"拼图需要 {cols}×{rows} = {cols * rows} 格，每格间隔 {interval:g} 秒，"
                        f"共要 {need:.0f} 秒画面；视频只有 {format_time(total, 1)}，"
                        f"最多只够 {max(1, int(total / interval))} 格。"
                        "请缩小网格或缩短抽取间隔。")
        return None

    # -- 进度预估 ---------------------------------------------------------
    def _int_or(self, value, default: int) -> int:
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return default

    def expected_duration(self, src: str) -> float | None:
        """各模式的实际处理范围，不能一律用源文件总时长。"""
        key = self._mode_key()
        if key == "gif":
            d = parse_time(self.gif_dur.get())
            return d if d and d > 0 else None
        if key == "frame":
            # 单帧输出：进度基本瞬时完成，给一个极小时长即可
            return 0.001
        if key == "tile":
            return None
        if key == "seq":
            return None
        # frames：仍要读完整个源文件，按源时长推进
        return super().expected_duration(src)

    def expected_frames(self, src: str) -> int:
        """按各模式实际输出的画面数量预估，否则进度条会卡住。"""
        key = self._mode_key()
        if key in ("frame", "tile"):
            return 1
        if key == "gif":
            n = self.frames_from_fps(self.expected_duration(src), self.gif_fps.get())
            return n
        if key == "frames":
            # 按**当前这个文件**的时长估算张数：批量处理时各文件长度不同，
            # 统一用第一个文件的时长会算错（self.src_duration() 就是第一个文件）。
            info = self.app.get_info(src)
            total = float(info.duration) if info and info.duration else 0.0
            try:
                interval = float(self.interval.get())
            except ValueError:
                interval = 10.0
            if total <= 0 or interval <= 0:
                return 0
            count = max(1, int(total / interval))
            limit = self._int_or(self.max_count.get(), 0)
            if limit > 0:
                count = min(count, limit)
            return count
        if key == "seq":
            return self._count_sequence_files()
        return super().expected_frames(src)

    def _count_sequence_files(self) -> int:
        """统计图片序列模板实际匹配到多少个文件（用于按帧显示进度）。

        ffmpeg 用 ``%04d`` 之类的占位符表示序号，glob 认不出这种写法，
        直接 glob 会恒返回 0（进度条只能退化成「处理中」动画），
        所以先把占位符换成通配符再去匹配。
        """
        pattern = self.seq_pattern.get().strip()
        if not pattern:
            return 0
        import glob as _glob
        import re as _re

        glob_pattern = _re.sub(r"%0?\d*[di]", "*", pattern)
        try:
            return len(_glob.glob(glob_pattern))
        except Exception:
            return 0

    # ------------------------------------------------------------------
    def build_cmd(self, src: str, dst: str) -> list[str]:
        key = self._mode_key()

        if key == "frame":
            t = parse_time(self.time.get()) or 0.0
            args = ["-ss", format_time(t, 3), "-i", src, "-frames:v", "1"]
            vf = self._scale_filter()
            if vf:
                args += ["-vf", vf]
            if self.img_fmt.get() == "jpg":
                args += ["-q:v", self.quality.get().strip() or "2"]
            return args + [dst]

        if key == "frames":
            try:
                interval = max(0.001, float(self.interval.get()))
            except ValueError:
                interval = 10.0
            args = ["-i", src, "-vf", f"fps=1/{interval}"]
            vf_scale = self._scale_filter()
            if vf_scale:
                args = ["-i", src, "-vf", f"fps=1/{interval},{vf_scale}"]
            if self.img_fmt.get() == "jpg":
                args += ["-q:v", self.quality.get().strip() or "2"]
            try:
                limit = int(float(self.max_count.get()))
            except ValueError:
                limit = 0
            if limit > 0:
                args += ["-frames:v", str(limit)]
            return args + [dst]

        if key == "tile":
            try:
                interval = max(0.001, float(self.interval.get()))
                cols = max(1, int(self.tile_cols.get()))
                rows = max(1, int(self.tile_rows.get()))
                width = max(16, int(self.tile_width.get()))
            except ValueError:
                interval, cols, rows, width = 10.0, 4, 4, 320
            vf = f"fps=1/{interval},scale={width}:-1,tile={cols}x{rows}"
            return ["-i", src, "-vf", vf, "-frames:v", "1", "-q:v", "3", dst]

        if key == "gif":
            start = parse_time(self.gif_start.get()) or 0.0
            dur = parse_time(self.gif_dur.get()) or 5.0
            fps = self.gif_fps.get().strip() or "12"
            width = self.gif_width.get().strip() or "480"
            vf = (f"fps={fps},scale={width}:-1:flags=lanczos,"
                  f"split[a][b];[a]palettegen=max_colors=256[p];[b][p]paletteuse=dither=bayer")
            args = []
            if start > 0:
                args += ["-ss", format_time(start, 3)]
            args += ["-t", format_time(dur, 3), "-i", src, "-vf", vf, "-loop", "0"]
            return args + [dst]

        # 图片序列 -> 视频
        pattern = src
        try:
            fps = self.seq_fps.get().strip() or "25"
        except Exception:
            fps = "25"
        args = ["-framerate", fps, "-i", pattern]
        vf = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
        if self._scale_filter() and self.scale.get() != "原始尺寸":
            vf = self._scale_filter() + "," + vf
        args += ["-vf", vf]
        args += builder.video_encode_args("libx264", crf=18, preset="medium", pix_fmt="yuv420p")
        args += ["-movflags", "+faststart"]
        return args + [dst]

    def _scale_filter(self) -> str:
        v = self.scale.get()
        if v == "原始尺寸":
            return ""
        return builder.scale_filter(v, None, "fit")

