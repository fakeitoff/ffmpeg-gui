# -*- coding: utf-8 -*-
"""压缩 / 画质调整页。"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk

from core import builder
from core.util import human_size
from .base import BaseTab

STRATEGIES = [
    "质量优先（CRF 18）",
    "均衡（CRF 23，推荐）",
    "小体积（CRF 28）",
    "自定义 CRF",
    "指定视频码率",
    "指定目标体积（MB）",
]

RESOLUTIONS = [
    ("保持原始分辨率", 0, 0),
    ("3840 × 2160  (4K UHD)", 3840, 2160),
    ("2560 × 1440  (2K QHD)", 2560, 1440),
    ("1920 × 1080  (1080p)", 1920, 1080),
    ("1280 × 720   (720p)", 1280, 720),
    ("854 × 480    (480p)", 854, 480),
    ("640 × 360    (360p)", 640, 360),
]

FPS_CHOICES = ["保持原始帧率", "60", "50", "30", "25", "24", "15", "自定义"]

CONTAINERS = [
    "mp4  |  MP4",
    "mkv  |  MKV",
    "mov  |  MOV",
    "webm  |  WebM",
]


def _key(choice: str) -> str:
    return choice.split("|")[0].strip()


class CompressTab(BaseTab):
    name = "压缩 / 画质"
    hint = ("通过 CRF、码率或目标体积控制输出大小，可同时缩放分辨率与限制帧率。"
            "CRF 越小画质越好、体积越大；0 为无损，51 为最差。")
    accept = "video"
    suffix = "_compressed"

    # ------------------------------------------------------------------
    def build(self):
        f = self.form
        self.strategy = tk.StringVar(value=STRATEGIES[1])
        self.crf = tk.IntVar(value=23)
        self.vbitrate = tk.StringVar(value="2000k")
        self.target_mb = tk.StringVar(value="20")
        self.venc = tk.StringVar(value="libx264")
        self.preset = tk.StringVar(value="medium")
        self.container = tk.StringVar(value=CONTAINERS[0])

        self.resolution = tk.StringVar(value=RESOLUTIONS[0][0])
        self.rw = tk.StringVar(value="1920")
        self.rh = tk.StringVar(value="1080")
        self.scale_mode = tk.StringVar(value="fit  |  等比缩放（保持比例，尺寸自适应）")
        self.fps = tk.StringVar(value=FPS_CHOICES[0])
        self.fps_custom = tk.StringVar(value="30")

        self.audio_mode = tk.StringVar(value="copy")
        self.abr = tk.StringVar(value="128k")
        self.faststart = tk.BooleanVar(value=True)
        self.hw_accel = tk.BooleanVar(value=False)

        f.combo("压缩策略", self.strategy, STRATEGIES, width=26, on_change=self._on_strategy)

        self.crf_scale = f.scale("CRF 画质", self.crf, 0, 51, on_change=self._on_crf,
                                 width=320, extra=self._add_crf_hint)
        self.crf.trace_add("write", lambda *a: self._update_hint())

        self.br_entry = f.entry("视频码率", self.vbitrate, width=12)
        self.size_entry = f.entry("目标体积", self.target_mb, width=12,
                                  extra=self._mb_extra)

        f.section("输出规格")
        f.combo("输出容器", self.container, CONTAINERS, width=20)
        self.venc_cb = f.combo("视频编码", self.venc, ["libx264"], width=34, on_change=self._on_encoder)
        self.preset_cb = f.combo("编码速度", self.preset, builder.PRESETS, width=18)

        self.res_cb = f.combo("分辨率", self.resolution, [r[0] for r in RESOLUTIONS] + ["自定义"],
                              width=30, on_change=self._on_resolution)
        self.custom_row = f.field("自定义尺寸")
        ttk.Entry(self.custom_row, textvariable=self.rw, width=8).grid(row=0, column=0, sticky="w")
        ttk.Label(self.custom_row, text="×", style="PanelMuted.TLabel").grid(row=0, column=1, padx=4)
        ttk.Entry(self.custom_row, textvariable=self.rh, width=8).grid(row=0, column=2, sticky="w")

        f.combo("缩放方式", self.scale_mode,
                ["fit  |  等比缩放（保持比例，尺寸自适应）",
                 "pad  |  等比缩放 + 补黑边（严格尺寸）",
                 "crop  |  等比放大 + 裁剪（填满画面）",
                 "stretch  |  强制拉伸（不保持比例）"], width=34)

        f.combo("帧率", self.fps, FPS_CHOICES, width=30, on_change=self._on_fps)
        self.fps_entry = f.entry("自定义帧率", self.fps_custom, width=10)

        f.section("音频")
        f.combo("音频处理", self.audio_mode,
                ["copy  |  直接复制", "aac  |  AAC 重新编码", "libmp3lame  |  MP3",
                 "libopus  |  Opus", "none  |  移除音频"], width=30, on_change=self._on_audio)
        self.abr_entry = f.entry("音频码率", self.abr, width=10)

        f.section("其他")
        f.check("", self.faststart, "MP4 快速网络播放（+faststart）")
        f.check("", self.hw_accel, "启用硬件解码加速（-hwaccel auto，需显卡支持）")

        self._on_strategy()

    # ------------------------------------------------------------------
    def _mb_extra(self, parent, col):
        ttk.Label(parent, text="MB", style="PanelMuted.TLabel").grid(row=0, column=col, padx=(6, 0))

    def _add_crf_hint(self, holder, col):
        """把 CRF 说明文字放进滑块所在容器，避免和同行控件叠在一起。"""
        self.crf_hint = ttk.Label(holder, text="", style="PanelMuted.TLabel")
        self.crf_hint.grid(row=0, column=col, padx=(14, 0))

    def _on_strategy(self):
        s = self.strategy.get()
        crf_active = s.startswith(("质量优先", "均衡", "小体积", "自定义"))
        if s.startswith("质量优先"):
            self.crf.set(18)
        elif s.startswith("均衡"):
            self.crf.set(23)
        elif s.startswith("小体积"):
            self.crf.set(28)
        self.crf_scale.configure(state="normal" if crf_active else "disabled")
        self.br_entry.configure(state="normal" if s.startswith("指定视频码率") else "disabled")
        self.size_entry.configure(state="normal" if s.startswith("指定目标体积") else "disabled")
        self.preset_cb.configure(state="disabled" if _key(self.venc.get()) == "copy" else "readonly")
        self._update_hint()

    def _on_crf(self, *_a):
        self._update_hint()

    def _update_hint(self):
        try:
            v = int(self.crf.get())
        except (tk.TclError, ValueError):
            return
        text = ("接近无损" if v <= 15 else "视觉无损" if v <= 19 else
                "均衡（推荐）" if v <= 24 else "体积优先" if v <= 29 else "低画质预览")
        self.crf_hint.configure(text=f"CRF {v} · {text}")

    def _on_encoder(self):
        self.preset_cb.configure(state="disabled" if _key(self.venc.get()) == "copy" else "readonly")

    def _on_resolution(self):
        if self.resolution.get() != "自定义":
            for name, w, h in RESOLUTIONS:
                if name == self.resolution.get() and w:
                    self.rw.set(str(w))
                    self.rh.set(str(h))
                    break

    def _on_fps(self):
        v = self.fps.get()
        if v not in ("保持原始帧率", "自定义"):
            self.fps_custom.set(v)

    def _on_audio(self):
        self.abr_entry.configure(
            state="disabled" if self.audio_mode.get().startswith(("copy", "none")) else "normal")

    def on_src_changed(self):
        values = []
        for enc in ("libx264", "libx265", "libsvtav1", "h264_nvenc", "hevc_nvenc",
                    "h264_qsv", "hevc_qsv", "h264_amf", "hevc_amf"):
            if enc in self.app.encoders:
                label = dict(builder.VIDEO_ENCODERS).get(enc, enc)
                values.append(f"{enc}  |  {label}")
        if values:
            self.venc_cb.configure(values=values)
            if _key(self.venc.get()) not in [_key(v) for v in values]:
                self.venc.set(values[0])
        if self.info and self.info.size:
            self.app.set_hint(f"源文件 {human_size(self.info.size)}，"
                              f"{self.info.describe()}")

    def output_ext(self) -> str:
        return _key(self.container.get())

    # ------------------------------------------------------------------
    def validate(self):
        if self.strategy.get().startswith("指定目标体积"):
            try:
                mb = float(self.target_mb.get())
            except ValueError:
                return "目标体积需要填写数字（单位 MB）。"
            if mb <= 0:
                return "目标体积必须大于 0。"
            if not self.src_duration():
                return "无法读取源文件时长，不能按目标体积压缩，请改用码率模式。"
        if self.strategy.get().startswith("指定视频码率"):
            if not self.vbitrate.get().strip():
                return "请填写视频码率，例如 2000k 或 2M。"
        return None

    def _resolve_bitrate(self) -> str | None:
        """根据策略返回视频码率字符串（如 ``2000k``），None 表示用 CRF。"""
        s = self.strategy.get()
        if s.startswith("指定视频码率"):
            return self.vbitrate.get().strip()
        if s.startswith("指定目标体积"):
            duration = self.src_duration()
            if not duration or duration <= 0:
                return None
            try:
                target_bytes = float(self.target_mb.get()) * 1024 * 1024
            except ValueError:
                return None
            total_kbps = (target_bytes * 8 / duration) / 1000.0
            audio_kbps = 0.0
            if not self.audio_mode.get().startswith("none"):
                if self.audio_mode.get().startswith("copy"):
                    audio_kbps = (self.info.audio.bit_rate / 1000.0) if (self.info and self.info.audio
                                                                        and self.info.audio.bit_rate) else 128.0
                else:
                    audio_kbps = self._parse_kbps(self.abr.get())
            video_kbps = total_kbps - audio_kbps
            if video_kbps < 50:
                return "50k"
            return f"{int(video_kbps)}k"
        return None

    @staticmethod
    def _parse_kbps(text: str) -> float:
        t = (text or "").strip().lower()
        try:
            if t.endswith("k"):
                return float(t[:-1])
            if t.endswith("m"):
                return float(t[:-1]) * 1000
            return float(t) / 1000.0
        except ValueError:
            return 128.0

    def build_cmd(self, src: str, dst: str) -> list[str]:
        venc = _key(self.venc.get())
        container = _key(self.container.get())
        bitrate = self._resolve_bitrate()

        args: list[str] = []
        if self.hw_accel.get():
            args += ["-hwaccel", "auto"]
        args += ["-i", src]

        # 视频编码
        vargs = builder.video_encode_args(
            venc,
            crf=None if bitrate else self.crf.get(),
            bitrate=bitrate,
            preset=self.preset.get(),
            pix_fmt="yuv420p" if (venc in ("libx264", "libx265") and container in ("mp4", "mov")) else None,
        )
        # 目标码率模式下增加峰值限制，避免局部码率飙升
        if bitrate and ("x264" in venc or "x265" in venc):
            kbps = int(self._parse_kbps(bitrate))
            vargs += ["-maxrate", f"{int(kbps * 1.5)}k", "-bufsize", f"{kbps * 2}k"]
        args += vargs

        # 滤镜链：缩放 + 帧率
        filters = []
        width, height = self._resolved_size()
        if width or height:
            filters.append(builder.scale_filter(width, height, _key(self.scale_mode.get())))
        if filters:
            args += ["-vf", ",".join(filters)]

        fps = self._resolved_fps()
        if fps:
            args += ["-r", fps]

        # 音频
        amode = _key(self.audio_mode.get())
        if amode == "none":
            args += ["-an"]
        else:
            args += builder.audio_encode_args(amode, bitrate=self.abr.get().strip() or None)

        if container == "mp4" and self.faststart.get():
            args += ["-movflags", "+faststart"]

        return args + [dst]

    def _resolved_size(self):
        if self.resolution.get() == "自定义":
            w = self.rw.get().strip()
            h = self.rh.get().strip()
            return (w or None), (h or None)
        for name, w, h in RESOLUTIONS:
            if name == self.resolution.get():
                return (w or None), (h or None)
        return None, None

    def _resolved_fps(self):
        v = self.fps.get()
        if v == "保持原始帧率":
            return None
        if v == "自定义":
            return self.fps_custom.get().strip() or None
        return v
