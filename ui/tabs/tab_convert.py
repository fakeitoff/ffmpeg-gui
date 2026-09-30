# -*- coding: utf-8 -*-
"""格式转换页。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from core import builder
from .base import BaseTab

VIDEO_FORMATS = [
    "mp4  |  MP4 —— 通用性最好，网页/手机/剪辑软件通吃",
    "mkv  |  MKV —— 万能容器，可装任意音轨与字幕",
    "mov  |  MOV —— 苹果 QuickTime 生态",
    "webm  |  WebM —— 网页开源格式（VP9/AV1）",
    "avi  |  AVI —— 兼容老设备与老软件",
    "flv  |  FLV —— 直播 / 老网站",
    "ts  |  TS —— 数字电视 / 流媒体切片",
    "wmv  |  WMV —— Windows Media",
    "ogv  |  OGV —— Theora 开源格式",
    "gif  |  GIF —— 动图（无声音，体积大）",
]

AUDIO_FORMATS = [
    "mp3  |  MP3 —— 通用有损音频",
    "m4a  |  M4A —— AAC 封装，苹果设备常用",
    "aac  |  AAC —— 裸流，体积小",
    "wav  |  WAV —— 无压缩 PCM，体积大",
    "flac  |  FLAC —— 无损压缩",
    "ogg  |  OGG —— Vorbis 开源",
    "opus  |  OPUS —— 低码率下音质最好",
    "wma  |  WMA —— Windows Media",
    "ac3  |  AC3 —— 杜比数字，家庭影院",
    "mka  |  MKA —— 无损音频容器",
]

CRF_DESC = {
    (0, 15): "接近无损，体积很大",
    (16, 19): "视觉无损，推荐归档",
    (20, 24): "画质与体积均衡（推荐）",
    (25, 29): "体积优先，轻微画质损失",
    (30, 100): "明显压缩，仅适合预览",
}


def _key(choice: str) -> str:
    return choice.split("|")[0].strip()


class ConvertTab(BaseTab):
    name = "格式转换"
    hint = ("把文件换一个容器或编码格式。视频/音频编码选 copy 表示不重新编码，"
            "只重新封装，速度极快且无画质损失（要求目标容器兼容原编码）。")
    accept = "any"
    suffix = "_conv"

    # ------------------------------------------------------------------
    def build(self):
        f = self.form
        self.kind = tk.StringVar(value="video")
        self.fmt = tk.StringVar(value=VIDEO_FORMATS[0])
        self.venc = tk.StringVar(value="libx264")
        self.aenc = tk.StringVar(value="aac")
        self.crf = tk.IntVar(value=23)
        self.preset = tk.StringVar(value="medium")
        self.abr = tk.StringVar(value="192k")
        self.faststart = tk.BooleanVar(value=True)
        self.keep_all = tk.BooleanVar(value=False)
        self.keep_meta = tk.BooleanVar(value=True)
        self.gif_fps = tk.StringVar(value="12")
        self.gif_width = tk.StringVar(value="640")

        f.radios("输出类型", self.kind, [("video", "视频"), ("audio", "纯音频")],
                 on_change=self._on_kind)

        self.fmt_cb = f.combo("输出格式", self.fmt, VIDEO_FORMATS, width=46,
                              on_change=self._on_format)

        self.venc_cb = f.combo("视频编码", self.venc, ["copy"],
                               width=34, on_change=self._on_encoder)
        self.aenc_cb = f.combo("音频编码", self.aenc, ["aac"], width=34)

        f.section("画质与速度")
        self.crf_scale = f.scale("视频质量", self.crf, 0, 51, on_change=self._on_crf, width=320)
        self.crf_hint = ttk.Label(self.form_holder, text="", style="PanelMuted.TLabel")
        self.crf_hint.grid(row=self.form.row - 1, column=1, sticky="e")
        self.crf.trace_add("write", lambda *a: self._update_crf_hint())

        self.preset_cb = f.combo("编码速度", self.preset, builder.PRESETS, width=18)
        f.note("越靠左编码越快、体积越大；slow 及以上压缩率更好但耗时明显增加。")
        f.entry("音频码率", self.abr, width=10)

        f.section("GIF 专用（仅输出 GIF 时生效）")
        f.entry("帧率", self.gif_fps, width=8, extra=self._gif_extra)
        f.section("其他选项")
        f.check("", self.faststart, "MP4 快速网络播放（+faststart，边下边播）")
        f.check("", self.keep_all, "保留全部音轨与字幕（推荐 MKV）")
        f.check("", self.keep_meta, "保留元数据（标题/作者等信息）")

        self._on_kind()

    # ------------------------------------------------------------------
    def _gif_extra(self, parent, col):
        ttk.Label(parent, text="宽  ", style="PanelMuted.TLabel").grid(row=0, column=col)
        ttk.Entry(parent, textvariable=self.gif_width, width=8).grid(row=0, column=col + 1, padx=(4, 0))

    def _on_kind(self):
        values = VIDEO_FORMATS if self.kind.get() == "video" else AUDIO_FORMATS
        self.fmt_cb.configure(values=values)
        if self.fmt.get() not in values:
            self.fmt.set(values[0])
        self._on_format()

    def _on_format(self, reset: bool = True):
        container = _key(self.fmt.get())
        video_only = self.kind.get() == "video"

        if video_only:
            cands = ["copy"] + list(builder.CONTAINER_VIDEO.get(container, ["libx264"]))
            vlist = [self._label(c, builder.VIDEO_ENCODERS) for c in cands
                     if c == "copy" or c in self.app.encoders]
            if not vlist:
                vlist = ["copy  |  直接复制（不重新编码）"]
            self.venc_cb.configure(values=vlist, state="readonly")
            if reset or _key(self.venc.get()) not in [_key(v) for v in vlist]:
                self.venc.set(vlist[1] if len(vlist) > 1 else vlist[0])
        else:
            self.venc_cb.configure(values=["（纯音频，不使用视频编码）"], state="disabled")

        if video_only:
            cands = ["copy"] + list(builder.CONTAINER_AUDIO.get(container, ["aac"]))
        else:
            default = builder.AUDIO_ONLY_FORMATS.get(container, ("aac", ""))[0]
            cands = ["copy", default] + [e for e in ("aac", "libmp3lame", "libopus",
                                                     "libvorbis", "flac", "pcm_s16le")
                                         if e != default]
        alist = [self._label(c, builder.AUDIO_ENCODERS) for c in cands
                 if c == "copy" or c in self.app.encoders]
        if not alist:
            alist = ["copy  |  直接复制（不重新编码）"]
        self.aenc_cb.configure(values=alist, state="readonly")
        if reset or _key(self.aenc.get()) not in [_key(v) for v in alist]:
            self.aenc.set(alist[1] if len(alist) > 1 else alist[0])

        self._on_encoder()
        self.notify_output_changed()

    @staticmethod
    def _label(encoder: str, table) -> str:
        if encoder == "copy":
            return "copy  |  直接复制（不重新编码）"
        return f"{encoder}  |  {dict(table).get(encoder, encoder)}"

    def _on_encoder(self):
        copy = _key(self.venc.get()) == "copy"
        state = "disabled" if (copy or self.kind.get() == "audio") else "normal"
        self.crf_scale.configure(state=state)
        self.preset_cb.configure(state="readonly" if state == "normal" else "disabled")

    def _on_crf(self, *_a):
        self._update_crf_hint()

    def _update_crf_hint(self):
        try:
            v = int(self.crf.get())
        except (tk.TclError, ValueError):
            return
        text = next((t for (lo, hi), t in CRF_DESC.items() if lo <= v <= hi), "")
        self.crf_hint.configure(text=f"CRF {v} · {text}")

    # ------------------------------------------------------------------
    def on_src_changed(self):
        self._update_crf_hint()

    def output_ext(self) -> str:
        return _key(self.fmt.get())

    # ------------------------------------------------------------------
    def validate(self):
        if self.kind.get() == "audio" and self.info and not self.info.has_audio:
            return "源文件不包含音频流，无法提取为纯音频格式。"
        if _key(self.fmt.get()) == "gif" and self.kind.get() == "video":
            pass
        return None

    def build_cmd(self, src: str, dst: str) -> list[str]:
        container = _key(self.fmt.get())
        venc = _key(self.venc.get())
        aenc = _key(self.aenc.get())
        args = ["-i", src]

        # ---- GIF 动图：使用调色板生成，画质远好于默认 ----
        if self.kind.get() == "video" and container == "gif":
            fps = self.gif_fps.get().strip() or "12"
            width = self.gif_width.get().strip() or "640"
            vf = (f"fps={fps},scale={width}:-1:flags=lanczos,"
                  f"split[s0][s1];[s0]palettegen=max_colors=256[p];"
                  f"[s1][p]paletteuse=dither=bayer:bayer_scale=3")
            return args + ["-vf", vf, "-loop", "0", "-an", dst]

        # ---- 纯音频 ----
        if self.kind.get() == "audio":
            args += ["-vn"]
            args += builder.audio_encode_args(aenc, bitrate=self.abr.get().strip() or None)
            if not self.keep_meta.get():
                args += ["-map_metadata", "-1"]
            return args + [dst]

        # ---- 视频 ----
        if self.keep_all.get():
            args += ["-map", "0", "-c", "copy"]
            args += builder.video_encode_args(venc, crf=self.crf.get(), preset=self.preset.get())
            args += builder.audio_encode_args(aenc, bitrate=self.abr.get().strip() or None)
        else:
            args += builder.video_encode_args(venc, crf=self.crf.get(), preset=self.preset.get())
            args += builder.audio_encode_args(aenc, bitrate=self.abr.get().strip() or None)

        if container == "mp4" and self.faststart.get():
            args += ["-movflags", "+faststart"]
        if not self.keep_meta.get():
            args += ["-map_metadata", "-1"]
        return args + [dst]
