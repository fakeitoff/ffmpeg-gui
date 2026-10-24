# -*- coding: utf-8 -*-
"""音频处理页：提取 / 替换 / 混音 / 滤镜。"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk

from core import builder
from .. import widgets
from .base import BaseTab

EXTRACT_FORMATS = [
    "mp3  |  MP3 —— 通用有损",
    "m4a  |  M4A —— AAC 封装",
    "aac  |  AAC —— 裸流",
    "wav  |  WAV —— 无损 PCM",
    "flac  |  FLAC —— 无损压缩",
    "ogg  |  OGG —— Vorbis",
    "opus  |  OPUS —— 低码率优选",
    "wma  |  WMA",
    "ac3  |  AC3 —— 杜比数字",
]

MODES = [
    ("extract", "提取音频（输出纯音频文件）"),
    ("replace", "替换音轨（用外部音频替换）"),
    ("mix", "混音（原声 + 背景音乐）"),
    ("mux", "合并音视频（视频本身无声音）"),
    ("remove", "移除音频（静音视频）"),
]

SAMPLE_RATES = ["保持原始", "8000", "16000", "22050", "32000", "44100", "48000", "96000"]
CHANNELS = ["保持原始", "1（单声道）", "2（立体声）"]


def _key(choice: str) -> str:
    return choice.split("|")[0].strip()


class AudioTab(BaseTab):
    name = "音频处理"
    hint = ("提取音轨、替换或混合背景音乐，以及音量、淡入淡出、延迟、重采样、"
            "降噪与响度标准化等常用音频处理。")
    accept = "any"
    suffix = "_audio"

    # ------------------------------------------------------------------
    def build(self):
        f = self.form
        self.mode = tk.StringVar(value="extract")
        self.fmt = tk.StringVar(value=EXTRACT_FORMATS[0])
        self.abr = tk.StringVar(value="192k")
        self.sample_rate = tk.StringVar(value=SAMPLE_RATES[0])
        self.channels = tk.StringVar(value=CHANNELS[0])
        self.out_fmt = tk.StringVar(value="保持原格式")

        self.audio_file = tk.StringVar(value="")
        self.bgm_volume = tk.StringVar(value="0.3")

        f.radios("处理方式", self.mode, MODES, on_change=self._on_mode)

        self.extract_box = f.field("输出音频格式")
        self.fmt_cb = ttk.Combobox(self.extract_box, textvariable=self.fmt,
                                   values=EXTRACT_FORMATS, width=30, state="readonly")
        self.fmt_cb.grid(row=0, column=0, sticky="w")

        self.file_row = f.field("外部音频文件")
        ttk.Entry(self.file_row, textvariable=self.audio_file).grid(row=0, column=0, sticky="ew")
        ttk.Button(self.file_row, text="浏览…", width=7, command=self._pick_audio).grid(
            row=0, column=1, padx=(6, 0))

        self.bgm_row = f.entry("背景音乐音量", self.bgm_volume, width=10,
                               extra=lambda p, c: ttk.Label(
                                   p, text="0 ~ 1，建议 0.2 ~ 0.4（仅混音模式）",
                                   style="PanelMuted.TLabel").grid(row=0, column=c, padx=(10, 0)))

        f.entry("音频码率", self.abr, width=10)
        f.combo("采样率", self.sample_rate, SAMPLE_RATES, width=16)
        f.combo("声道", self.channels, CHANNELS, width=16)
        self.out_fmt_cb = f.combo("输出容器", self.out_fmt, ["保持原格式", "mp4", "mkv", "mov"],
                                  width=16, on_change=self.notify_output_changed)

        f.section("音频滤镜")
        self.vol_mode = tk.StringVar(value="倍率")
        self.vol_value = tk.StringVar(value="1.0")
        vol_row = f.field("音量")
        ttk.Combobox(vol_row, textvariable=self.vol_mode, values=["倍率", "分贝(dB)"],
                     width=10, state="readonly").grid(row=0, column=0, sticky="w")
        ttk.Entry(vol_row, textvariable=self.vol_value, width=10).grid(row=0, column=1, padx=(8, 0))
        ttk.Label(vol_row, text="倍率如 1.5 / 0.5；分贝如 +6 或 -3", style="PanelMuted.TLabel").grid(
            row=0, column=2, padx=(10, 0))

        self.fade_in = tk.StringVar(value="")
        self.fade_out = tk.StringVar(value="")
        self.delay_ms = tk.StringVar(value="")
        fade_row = f.field("淡入 / 淡出")
        ttk.Entry(fade_row, textvariable=self.fade_in, width=8).grid(row=0, column=0)
        ttk.Label(fade_row, text="秒 淡入   淡出", style="PanelMuted.TLabel").grid(row=0, column=1, padx=(6, 6))
        ttk.Entry(fade_row, textvariable=self.fade_out, width=8).grid(row=0, column=2)
        ttk.Label(fade_row, text="秒", style="PanelMuted.TLabel").grid(row=0, column=3, padx=(6, 0))

        f.entry("延迟", self.delay_ms, width=10,
                extra=lambda p, c: ttk.Label(p, text="毫秒，正数=延后播放", style="PanelMuted.TLabel").grid(
                    row=0, column=c, padx=(10, 0)))

        self.denoise = tk.BooleanVar(value=False)
        self.loudnorm = tk.BooleanVar(value=False)
        self.loudnorm_target = tk.StringVar(value="-16")
        self.highpass = tk.StringVar(value="")
        self.hp_row = f.check("", self.denoise, "降噪（fft 频域降噪，适合去除持续底噪）")
        f.check("", self.loudnorm, "响度标准化（统一到广播标准，适合多素材统一音量）")
        f.entry("目标响度", self.loudnorm_target, width=10,
                extra=lambda p, c: ttk.Label(p, text="LUFS，-16 适合网络 / -23 适合电视",
                                             style="PanelMuted.TLabel").grid(row=0, column=c, padx=(10, 0)))
        f.entry("高通滤波", self.highpass, width=10,
                extra=lambda p, c: ttk.Label(p, text="Hz，去除低频轰鸣（如 80）",
                                             style="PanelMuted.TLabel").grid(row=0, column=c, padx=(10, 0)))

        self._on_mode()

    # ------------------------------------------------------------------
    def _pick_audio(self):
        files = widgets.ask_open_files(self, widgets.AUDIO_TYPES, multiple=False)
        if files:
            self.audio_file.set(files[0])

    def _on_mode(self):
        mode = self.mode.get()
        st = "readonly" if mode == "extract" else "disabled"
        self.fmt_cb.configure(state=st)
        need_file = mode in ("replace", "mix", "mux")
        for child in self.file_row.winfo_children():
            try:
                child.configure(state="normal" if need_file else "disabled")
            except tk.TclError:
                pass
        for child in self.bgm_row.winfo_children():
            try:
                child.configure(state="normal" if mode == "mix" else "disabled")
            except tk.TclError:
                pass
        self.out_fmt_cb.configure(state="disabled" if mode == "extract" else "readonly")
        self.notify_output_changed()

    # ------------------------------------------------------------------
    def output_ext(self) -> str:
        mode = self.mode.get()
        if mode == "extract":
            return _key(self.fmt.get())
        if mode == "replace":
            v = self.out_fmt.get()
            if v == "保持原格式" and not self.has_video():
                return _key(self.fmt.get())
            return self.app.src_ext() if v == "保持原格式" else v
        return self.app.src_ext() or "mp4"

    def output_suffix(self) -> str:
        return "_audio" if self.mode.get() == "extract" else "_" + self.mode.get()

    # ------------------------------------------------------------------
    # -- 进度预估 ---------------------------------------------------------
    def expected_frames(self, src: str) -> int:
        """提取音频时输出没有视频流，帧数必须报 0，否则进度条会卡在 0%。

        其他模式（替换 / 混音 / 合并）都保留原视频流（-c:v copy），帧数不变。
        """
        if self.mode.get() == "extract":
            return 0
        return super().expected_frames(src)

    def _audio_filters(self, src: str = "") -> str:
        """拼出音频滤镜链。

        ``src`` 传入当前正在处理的文件：淡出起点要按**这个文件**的时长算，
        批量处理时各文件长度不同，统一用第一个文件会把淡出位置算错。
        """
        chain = []
        # 音量
        try:
            value = float(self.vol_value.get())
        except ValueError:
            value = 1.0
        if self.vol_mode.get() == "倍率":
            if abs(value - 1.0) > 1e-6:
                chain.append(f"volume={value:g}")
        else:
            if abs(value) > 1e-6:
                chain.append(f"volume={value:g}dB")
        # 延迟
        try:
            delay = float(self.delay_ms.get())
        except ValueError:
            delay = 0.0
        if delay > 0:
            chain.append(f"adelay={int(delay)}|{int(delay)}")
        # 高通
        hp = self.highpass.get().strip()
        if hp:
            chain.append(f"highpass=f={hp}")
        # 降噪
        if self.denoise.get():
            chain.append("afftdn=nf=-25")
        # 淡入淡出
        try:
            fin = float(self.fade_in.get())
        except ValueError:
            fin = 0.0
        try:
            fout = float(self.fade_out.get())
        except ValueError:
            fout = 0.0
        if fin > 0:
            chain.append(f"afade=t=in:st=0:d={fin:g}")
        if fout > 0:
            total = 0.0
            if src:
                info = self.app.get_info(src)
                total = float(info.duration) if info and info.duration else 0.0
            if not total:
                total = self.src_duration()
            st = max(0.0, total - fout) if total else 0
            chain.append(f"afade=t=out:st={st:.3f}:d={fout:g}")
        # 响度标准化
        if self.loudnorm.get():
            target = self.loudnorm_target.get().strip() or "-16"
            chain.append(f"loudnorm=I={target}:TP=-1.5:LRA=11")
        return ",".join(chain)

    def _encode_args(self) -> list[str]:
        mode = self.mode.get()
        if mode == "extract":
            fmt = _key(self.fmt.get())
            enc = dict(builder.AUDIO_ONLY_FORMATS).get(fmt, ("aac", "m4a"))[0]
            if enc not in self.app.encoders:
                enc = "aac"
        else:
            enc = "aac"
        sr = self.sample_rate.get()
        ch = self.channels.get()
        return builder.audio_encode_args(
            enc,
            bitrate=self.abr.get().strip() or None,
            sample_rate=None if sr == "保持原始" else sr,
            channels=None if ch == "保持原始" else ch.split("（")[0],
        )

    # ------------------------------------------------------------------
    def validate(self):
        mode = self.mode.get()
        if mode in ("replace", "mix", "mux"):
            path = self.audio_file.get().strip()
            if not path:
                return "请选择外部音频文件。"
            if not os.path.isfile(path):
                return f"外部音频文件不存在：{path}"
        if mode == "mix" and not self.has_audio():
            return "源文件没有音轨，无法混音，请改用「合并音视频」。"
        if mode == "remove" and not self.has_video():
            return "源文件不是视频文件，无需移除音频。"
        return None

    def build_cmd(self, src: str, dst: str) -> list[str]:
        mode = self.mode.get()
        af = self._audio_filters(src)
        enc_args = self._encode_args()

        if mode == "extract":
            args = ["-i", src, "-vn"]
            if af:
                args += ["-af", af]
            args += enc_args
            return args + [dst]

        if mode == "remove":
            return ["-i", src, "-an", "-c:v", "copy", dst]

        ext_audio = self.audio_file.get().strip()

        if mode == "mux":
            args = ["-i", src, "-i", ext_audio, "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy"] + enc_args + ["-shortest"]
            if af:
                args += ["-af", af]
            return args + [dst]

        if mode == "replace":
            args = ["-i", src, "-i", ext_audio]
            if af:
                args += ["-filter_complex", f"[1:a]{af}[aout]",
                         "-map", "0:v:0", "-map", "[aout]"]
            else:
                args += ["-map", "0:v:0", "-map", "1:a:0"]
            args += ["-c:v", "copy"] + enc_args + ["-shortest"]
            return args + [dst]

        # mix：原声 + 背景音乐
        args = ["-i", src, "-i", ext_audio]
        try:
            bg_vol = float(self.bgm_volume.get())
        except ValueError:
            bg_vol = 0.3
        fc = f"[1:a]volume={bg_vol:g}[bg];[0:a][bg]{self.amix_args(2, 'first')}"
        if af:
            fc += f"[mix];[mix]{af}[aout]"
        else:
            fc += "[aout]"
        args += ["-filter_complex", fc, "-map", "0:v:0", "-map", "[aout]",
                 "-c:v", "copy"] + enc_args + ["-shortest"]
        return args + [dst]
