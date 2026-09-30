# -*- coding: utf-8 -*-
"""剪辑 / 裁剪页。"""
from __future__ import annotations

import tkinter as tk

from core import builder
from core.util import format_time, parse_time
from .base import BaseTab

ROTATIONS = [
    "不旋转",
    "顺时针 90°",
    "逆时针 90°",
    "旋转 180°",
    "水平镜像",
    "垂直镜像",
]

FORMATS = ["保持原格式", "mp4", "mkv", "mov", "webm", "avi"]


class TrimTab(BaseTab):
    name = "剪辑 / 裁剪"
    hint = ("按时间截取片段，并可裁剪画面、旋转翻转。"
            "「快速」模式不重新编码、瞬间完成，但起点会对齐到最近的关键帧；"
            "「精确」模式重新编码，画面与时间点完全精确。")
    accept = "video"
    suffix = "_trim"
    default_ext = "mp4"

    # ------------------------------------------------------------------
    def build(self):
        f = self.form
        self.start = tk.StringVar(value="0")
        self.end = tk.StringVar(value="")
        self.dur = tk.StringVar(value="")
        self.mode = tk.StringVar(value="accurate")
        self.out_fmt = tk.StringVar(value=FORMATS[0])

        f.section("时间范围")
        f.time_row("起始时间", self.start, "格式 00:00:10.500，也可写 10.5")
        f.time_row("结束时间", self.end, "留空则截到结尾")
        f.time_row("持续时长", self.dur, "与「结束时间」二选一，优先使用")
        f.note("提示：结束时间与持续时长只需填写一个。若都填写，以「持续时长」为准。")

        f.radios("剪辑精度", self.mode,
                 [("fast", "快速（不重新编码，秒出）"),
                  ("accurate", "精确（重新编码）")])

        f.section("画面裁剪")
        self.crop_on = tk.BooleanVar(value=False)
        f.check("", self.crop_on, "启用裁剪（去掉画面边缘区域）")
        self.crop_w = tk.StringVar(value="1280")
        self.crop_h = tk.StringVar(value="720")
        self.crop_x = tk.StringVar(value="0")
        self.crop_y = tk.StringVar(value="0")
        row = f.field("裁剪区域")
        for label, var in (("宽", self.crop_w), ("高", self.crop_h),
                           ("X", self.crop_x), ("Y", self.crop_y)):
            tk.Label(row, text=label, bg="#ffffff", fg="#6b7280").pack(side="left", padx=(0, 3))
            tk.Entry(row, textvariable=var, width=6, relief="solid", borderwidth=1).pack(
                side="left", padx=(0, 12))

        f.section("旋转 / 翻转")
        self.rotation = tk.StringVar(value=ROTATIONS[0])
        f.combo("方向", self.rotation, ROTATIONS, width=18)
        self.angle = tk.StringVar(value="0")
        f.entry("任意角度", self.angle, width=10, browse=None,
                extra=lambda p, c: tk.Label(p, text="度，逆时针为正", bg="#ffffff",
                                            fg="#6b7280").grid(row=0, column=c, padx=(8, 0)))

        f.section("输出")
        f.combo("输出格式", self.out_fmt, FORMATS, width=18, on_change=self.notify_output_changed)

    # ------------------------------------------------------------------
    def output_ext(self) -> str:
        v = self.out_fmt.get()
        if v == "保持原格式":
            return self.app.src_ext() or "mp4"
        return v

    def _times(self):
        """返回 (start, duration) 秒，均可为 None。"""
        start = parse_time(self.start.get()) or 0.0
        if self.dur.get().strip():
            d = parse_time(self.dur.get())
            return start, (d if d and d > 0 else None)
        if self.end.get().strip():
            e = parse_time(self.end.get())
            if e is not None:
                return start, max(0.0, e - start)
        return start, None

    def _filters(self) -> list[str]:
        chained: list[str] = []
        if self.crop_on.get():
            w = self.crop_w.get().strip() or "iw"
            h = self.crop_h.get().strip() or "ih"
            x = self.crop_x.get().strip() or "0"
            y = self.crop_y.get().strip() or "0"
            chained.append(f"crop={w}:{h}:{x}:{y}")
        rot = self.rotation.get()
        chained += {
            "顺时针 90°": ["transpose=1"],
            "逆时针 90°": ["transpose=2"],
            "旋转 180°": ["transpose=2,transpose=2"],
            "水平镜像": ["hflip"],
            "垂直镜像": ["vflip"],
        }.get(rot, [])
        try:
            angle = float(self.angle.get() or 0)
        except ValueError:
            angle = 0.0
        if abs(angle) > 0.001:
            rad = angle * 3.141592653589793 / 180.0
            chained.append(f"rotate={rad:.6f}:ow=rotw({rad:.6f}):oh=roth({rad:.6f}):c=black")
        return chained

    # ------------------------------------------------------------------
    def validate(self):
        try:
            start, dur = self._times()
        except ValueError as exc:
            return str(exc)
        if start < 0:
            return "起始时间不能为负数。"
        total = self.src_duration()
        if total and start >= total:
            return f"起始时间超出视频长度（视频共 {format_time(total, 1)}）。"
        if dur is not None and dur <= 0:
            return "截取时长为 0，请检查结束时间是否大于起始时间。"
        return None

    def build_cmd(self, src: str, dst: str) -> list[str]:
        start, dur = self._times()
        start = start or 0.0
        filters = self._filters()
        accurate = self.mode.get() == "accurate"
        # 有滤镜时必须重新编码
        encode = accurate or bool(filters)

        args: list[str] = []
        if start > 0:
            args += ["-ss", format_time(start, 3)]
        args += ["-i", src]
        if dur:
            args += ["-t", format_time(dur, 3)]

        if filters:
            args += ["-vf", ",".join(filters)]

        if encode:
            args += builder.video_encode_args("libx264", crf=18, preset="veryfast", pix_fmt="yuv420p")
            # 直接指定音频编码器即可：源文件没有音轨时 ffmpeg 会自己忽略，
            # 不能用 ffprobe 的探测结果去决定 -an（探测未就绪/失败会静默丢音轨）
            args += ["-c:a", "aac", "-b:a", "192k"]
            args += ["-avoid_negative_ts", "make_zero"]
        else:
            args += ["-c", "copy", "-avoid_negative_ts", "make_zero"]

        if self.output_ext() == "mp4":
            args += ["-movflags", "+faststart"]
        return args + [dst]
