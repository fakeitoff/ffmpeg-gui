# -*- coding: utf-8 -*-
"""合并 / 拼接页：多段视频接成一段、音视频合并、多音轨封装、并排同屏。"""
from __future__ import annotations

import os
import re
import tkinter as tk
from tkinter import ttk

from core import builder, probe
from core.util import is_http_url, local_temp_dir
from .. import theme, widgets
from .base import BaseTab
from .subform import SubForm

# 操作类型：(键, 说明)
OPERATIONS = [
    ("concat", "首尾拼接 · 把多个视频接成一段"),
    ("hls", "m3u8 合成 · 播放列表 / 分片合成一个视频"),
    ("mux", "音视频合并 · 画面来自 A，声音来自 B"),
    ("multitrack", "多音轨封装 · 多个文件的音轨合进一个文件"),
    ("side", "并排同屏 · 两个视频左右 / 上下同屏"),
]
OP_KEY = {label: key for key, label in OPERATIONS}
OP_LABEL = {key: label for key, label in OPERATIONS}

CONTAINERS = ["保持原格式", "mp4", "mkv", "mov", "avi", "webm", "ts"]

RESOLUTIONS = [
    ("跟随第一个视频", 0, 0),
    ("1920 × 1080  (1080p)", 1920, 1080),
    ("1280 × 720   (720p)", 1280, 720),
    ("854 × 480    (480p)", 854, 480),
    ("640 × 360    (360p)", 640, 360),
]

FPS_CHOICES = ["跟随第一个视频", "60", "30", "25", "24", "保持各自帧率"]

TRANSITION_KEYS = ["fade", "wipeleft", "slideleft", "circlecrop", "dissolve", "smoothleft"]

SIDE_LAYOUTS = [("hstack", "左右并排"), ("vstack", "上下堆叠")]
SIDE_AUDIO = [("first", "保留第一个视频的声音"),
              ("mix", "混合两个视频的声音"),
              ("none", "静音")]

AUDIO_ENCODERS = ["aac", "libmp3lame", "libopus", "libvorbis", "flac", "pcm_s16le"]


class MergeTab(BaseTab):
    name = "合并 / 拼接"
    hint = ("把多个视频接成一段时，默认「直接拼接」不重新编码，只复制视频流与音频流，"
            "秒级完成且画质无损；只有各段分辨率或编码不一致时，才需要改用「兼容拼接」。"
            "拼接顺序就是主界面文件列表的顺序（可用 ↑ ↓ 调整）。\n"
            "「m3u8 合成」把播放列表变成一个普通视频文件：本地列表（分片同目录，"
            "支持 AES-128 加密分片），也可以直接填在线地址 http(s)://…m3u8 "
            "下载点播或录制直播；填了录制时长的会到点自停，没填的一直录到点「停止」。")
    accept = "video"
    suffix = "_merged"

    # ------------------------------------------------------------------
    def build(self):
        self._list_content = ""
        self._aux_files: list[str] = []
        # 我们替用户自动选过的容器（离开该操作时要还原成「保持原格式」）
        self._auto_container = ""      # 我们替用户选过的容器，离开操作时还原
        # 输出名改过一次，清单文件名就跟着变；旧的那些要一路记着才能删干净
        # （只记「当前这一个」会让改名预览留下的清单永远躺在 temp/ 里）。
        self._list_paths: set[str] = set()
        f = self.form

        self.operation = tk.StringVar(value=OP_LABEL["concat"])
        self.container = tk.StringVar(value=CONTAINERS[0])

        # 首尾拼接
        self.join_mode = tk.StringVar(value="copy")        # copy / reencode
        self.resolution = tk.StringVar(value=RESOLUTIONS[0][0])
        self.fps = tk.StringVar(value=FPS_CHOICES[0])
        self.venc = tk.StringVar(value="libx264")
        self.crf = tk.StringVar(value="20")
        self.preset = tk.StringVar(value="veryfast")
        self.aenc = tk.StringVar(value="aac")
        self.abr = tk.StringVar(value="192k")
        self.transition = tk.StringVar(value="fade")
        self.transition_on = tk.BooleanVar(value=False)
        self.transition_dur = tk.StringVar(value="1.0")
        self._venc_cbs: list[ttk.Combobox] = []

        # m3u8 合成
        self.hls_mode = tk.StringVar(value="copy")         # copy / reencode
        self.hls_url = tk.StringVar(value="")
        self.hls_ua = tk.StringVar(value="")
        self.hls_refer = tk.StringVar(value="")
        self.hls_record = tk.StringVar(value="")           # 录制时长（秒）；空 = 一直录
        self.hls_reconnect = tk.StringVar(value="")        # 重连退避上限（秒）；空 = 默认
        self._hls_info_cache: dict = {}

        # 音视频合并
        self.audio_file = tk.StringVar(value="")
        self.mux_aenc = tk.StringVar(value="copy")
        self.mux_abr = tk.StringVar(value="192k")
        self.mux_shortest = tk.BooleanVar(value=True)

        # 并排同屏
        self.side_file = tk.StringVar(value="")
        self.side_layout = tk.StringVar(value="hstack")
        self.side_audio = tk.StringVar(value="first")
        self.side_size = tk.StringVar(value=RESOLUTIONS[0][0])

        f.combo("操作类型", self.operation, [label for _k, label in OPERATIONS],
                width=40, on_change=self._on_operation)
        self.container_cb = f.combo("输出格式", self.container, CONTAINERS, width=16,
                                    on_change=self._update_hls_tip)

        self.box = ttk.Frame(self.form_holder, style="Panel.TFrame")
        self.box.grid(row=f.row, column=0, columnspan=2, sticky="ew")
        self.box.columnconfigure(1, weight=1)
        f.row += 1
        self._build_boxes()

        # 文件顺序预览
        self.order_holder = ttk.Frame(self.form_holder, style="Panel.TFrame")
        self.order_holder.grid(row=f.row, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.order_holder.columnconfigure(0, weight=1)
        f.row += 1
        ttk.Label(self.order_holder, text="将要处理的文件（按此顺序）",
                  style="Form.TLabel").grid(row=0, column=0, sticky="w")
        self.order_text = tk.Text(self.order_holder, height=4, wrap="none", bg="#fbfbfc",
                                  fg="#3b4148", relief="solid", borderwidth=1,
                                  font=("Consolas", 9), padx=8, pady=5, state="disabled")
        self.order_text.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        self._on_operation()

    # ------------------------------------------------------------------
    def _new_box(self):
        box = ttk.Frame(self.box, style="Panel.TFrame")
        box.grid(row=0, column=1, sticky="ew")
        box.columnconfigure(1, weight=1)
        return box

    def _encode_rows(self, g: SubForm):
        """视频 / 音频编码两行——兼容拼接与 m3u8 兼容合成共用同一组设置。"""
        row = g.field("视频编码")
        venc_cb = ttk.Combobox(row, textvariable=self.venc, values=["libx264"],
                               width=15, state="readonly")
        venc_cb.grid(row=0, column=0, sticky="w")
        self._venc_cbs.append(venc_cb)
        ttk.Label(row, text="CRF", style="PanelMuted.TLabel").grid(row=0, column=1, padx=(13, 4))
        ttk.Entry(row, textvariable=self.crf, width=5).grid(row=0, column=2, sticky="w")
        ttk.Label(row, text="速度", style="PanelMuted.TLabel").grid(row=0, column=3, padx=(13, 4))
        ttk.Combobox(row, textvariable=self.preset, values=builder.PRESETS, width=11,
                     state="readonly").grid(row=0, column=4, sticky="w")
        row = g.field("音频编码")
        ttk.Combobox(row, textvariable=self.aenc, values=AUDIO_ENCODERS, width=13,
                     state="readonly").grid(row=0, column=0, sticky="w")
        ttk.Label(row, text="码率", style="PanelMuted.TLabel").grid(row=0, column=1, padx=(13, 4))
        ttk.Entry(row, textvariable=self.abr, width=8).grid(row=0, column=2, sticky="w")

    def _build_boxes(self):
        # ---------------- 首尾拼接 ----------------
        self.concat_box = self._new_box()
        g = SubForm(self.concat_box)
        row = g.field("拼接方式")
        ttk.Radiobutton(row, text="直接拼接（复制视频流 + 音频流，不重新编码）",
                        value="copy", variable=self.join_mode,
                        command=self._on_join_mode).grid(row=0, column=0, sticky="w")
        row = g.field("")
        ttk.Radiobutton(row, text="兼容拼接（重新编码，自动统一分辨率与编码）",
                        value="reencode", variable=self.join_mode,
                        command=self._on_join_mode).grid(row=0, column=0, sticky="w")
        g.note("直接拼接要求各文件的分辨率、帧率、编码格式一致；不一致时请选择兼容拼接。\n"
               "拼接清单会临时写到程序目录的 temp/ 文件夹，任务结束自动删除，"
               "不使用系统盘的临时目录。")

        self.rec_box = ttk.Frame(self.concat_box, style="Panel.TFrame")
        self.rec_box.grid(row=g.row, column=0, columnspan=2, sticky="ew")
        self.rec_box.columnconfigure(1, weight=1)
        g.row += 1
        rg = SubForm(self.rec_box)
        rg.combo("统一分辨率", self.resolution, [r[0] for r in RESOLUTIONS], width=24)
        rg.combo("统一帧率", self.fps, FPS_CHOICES, width=24)
        self._encode_rows(rg)

        # 转场（整块显隐）
        self.trans_block = ttk.Frame(self.rec_box, style="Panel.TFrame")
        self.trans_block.grid(row=rg.row, column=0, columnspan=2, sticky="ew")
        self.trans_block.columnconfigure(1, weight=1)
        tg = SubForm(self.trans_block)
        tg.check("", self.transition_on, "添加转场效果（相邻片段之间过渡）",
                 on_change=self._on_transition)
        self.trans_row = tg.field("转场方式")
        ttk.Combobox(self.trans_row, textvariable=self.transition, values=TRANSITION_KEYS,
                     width=14, state="readonly").grid(row=0, column=0, sticky="w")
        ttk.Label(self.trans_row, text="时长", style="PanelMuted.TLabel").grid(
            row=0, column=1, padx=(13, 4))
        ttk.Entry(self.trans_row, textvariable=self.transition_dur, width=6).grid(
            row=0, column=2, sticky="w")
        ttk.Label(self.trans_row, text="秒（需小于最短片段的长度）",
                  style="PanelMuted.TLabel").grid(row=0, column=3, padx=(4, 0))

        # ---------------- m3u8 合成 ----------------
        self.hls_box = self._new_box()
        g = SubForm(self.hls_box)
        g.field_hint("在线地址", self.hls_url, width=58,
                     hint="http(s)://…/index.m3u8　填了就优先用它（下载 / 录制直播）")
        self.hls_url.trace_add("write", lambda *_a: self._on_url_changed())
        row = g.field("防盗链 UA")
        ttk.Entry(row, textvariable=self.hls_ua, width=44).grid(row=0, column=0, sticky="w")
        ttk.Button(row, text="浏览器 UA", width=10,
                   command=self._use_browser_ua).grid(row=0, column=1, padx=(6, 0))
        g.entry("Referer", self.hls_refer, width=58)
        g.field_hint("录制时长", self.hls_record, width=10,
                     hint="秒。留空 = 一直录到点「停止」（点播/已完成的直播不用填）")
        g.field_hint("重连等待", self.hls_reconnect, width=10,
                     hint="秒。断线后最长退避到这个时间再重连；留空按 "
                          f"{probe.HLS_RECONNECT_DEFAULT} 秒")
        row = g.field("本地列表")
        ttk.Label(row, text="未填在线地址时，用主界面已选的第一个 .m3u8 文件",
                  style="PanelMuted.TLabel").grid(row=0, column=0, sticky="w")
        row = g.field("合成方式")
        ttk.Radiobutton(row, text="直接合成（复制视频流 + 音频流，不重新编码）",
                        value="copy", variable=self.hls_mode,
                        command=self._on_hls_mode).grid(row=0, column=0, sticky="w")
        row = g.field("")
        ttk.Radiobutton(row, text="兼容合成（重新编码，分片编码不一致或要改格式时用）",
                        value="reencode", variable=self.hls_mode,
                        command=self._on_hls_mode).grid(row=0, column=0, sticky="w")

        self.hls_rec_box = ttk.Frame(self.hls_box, style="Panel.TFrame")
        self.hls_rec_box.grid(row=g.row, column=0, columnspan=2, sticky="ew")
        self.hls_rec_box.columnconfigure(1, weight=1)
        g.row += 1
        self._encode_rows(SubForm(self.hls_rec_box))

        self.hls_tip = ttk.Label(self.hls_box, text="", style="PanelMuted.TLabel",
                                 wraplength=widgets.scaled(self.hls_box, 640),
                                 justify="left")
        self.hls_tip.grid(row=g.row, column=0, columnspan=2, sticky="w", pady=(2, 0))
        g.row += 1

        g.note("m3u8 只是播放列表，画面数据都在分片里：本地列表要求分片同目录，"
               "在线地址则由 ffmpeg 现取现拼，默认不重新编码、画质无损。\n"
               "在线列表常做防盗链：只认浏览器 UA / Referer，实测不带会被服务端 403 拒绝，"
               "所以这两个框专门留出来（只发给 http(s) 输入，本地文件不能带这些参数）。\n"
               "断线会自动重试（「重连等待」是最长退避秒数），网络回来后**接着录后面的内容**；"
               "但要说清楚：断掉那几秒的分片服务端已经翻过去了，取不回来，"
               "实测结果是一个「中间缺几段」的短片，ffmpeg 仍会返回成功。"
               "填了「录制时长」时看进度条有没有走满，就能判断有没有缺。\n"
               "填了「录制时长」到点自动结束，没填就一直跟播，等你点「停止」"
               "（停止会让 ffmpeg 写完文件尾，已录的部分都保留）。\n"
               "直播流（列表里没有 ENDLIST）会一直跟播：想停就点「停止」，"
               "程序会让 ffmpeg 自己收尾（实测 mp4 / mkv 都能完整退出、文件可播），"
               "已录下多少就存下多少。\n"
               "边下边播请选 mkv 或 ts：mp4 的文件尾（moov）要等写完才存在，"
               "实测录制中途打开会报 moov atom not found，打不开。")

        # ---------------- 音视频合并 ----------------
        self.mux_box = self._new_box()
        g = SubForm(self.mux_box)
        row = g.field("画面来源")
        ttk.Label(row, text="主界面已选的第一个文件", style="PanelMuted.TLabel").grid(
            row=0, column=0, sticky="w")
        g.file_row("声音来源", self.audio_file, self._pick_audio, None, "提供音频的文件")
        row = g.field("音频流")
        ttk.Combobox(row, textvariable=self.mux_aenc,
                     values=["copy"] + AUDIO_ENCODERS, width=13,
                     state="readonly").grid(row=0, column=0, sticky="w")
        ttk.Label(row, text="码率", style="PanelMuted.TLabel").grid(row=0, column=1, padx=(13, 4))
        ttk.Entry(row, textvariable=self.mux_abr, width=8).grid(row=0, column=2, sticky="w")
        g.check("", self.mux_shortest, "裁剪到视频长度（画面结束时声音也结束）")
        g.note("视频流始终直接复制，不重新编码，画质无损。")

        # ---------------- 多音轨封装 ----------------
        self.mt_box = self._new_box()
        g = SubForm(self.mt_box)
        row = g.field("主文件")
        ttk.Label(row, text="主界面已选的第一个文件（提供画面）",
                  style="PanelMuted.TLabel").grid(row=0, column=0, sticky="w")
        row = g.field("附加音轨")
        self.extra_list = widgets.FileListBox(row, widgets.MEDIA_TYPES,
                                              title="选择要并入的音轨 / 字幕文件",
                                              height=4, multiple=True)
        self.extra_list.grid(row=0, column=0, sticky="ew")
        g.note("所有音轨与字幕都会直接复制进同一个文件，不重新编码；"
               "推荐输出 MKV（MP4 对多音轨与字幕支持较差）。")

        # ---------------- 并排同屏 ----------------
        self.side_box = self._new_box()
        g = SubForm(self.side_box)
        row = g.field("第一路画面")
        ttk.Label(row, text="主界面已选的第一个文件", style="PanelMuted.TLabel").grid(
            row=0, column=0, sticky="w")
        g.file_row("第二路画面", self.side_file, self._pick_side, None, "另一个视频文件")
        g.radio_row("排列方式", self.side_layout, SIDE_LAYOUTS)
        g.combo("统一高度/宽度", self.side_size, [r[0] for r in RESOLUTIONS], width=24)
        g.radio_row("声音", self.side_audio, SIDE_AUDIO)

        self._boxes = {
            "concat": self.concat_box,
            "hls": self.hls_box,
            "mux": self.mux_box,
            "multitrack": self.mt_box,
            "side": self.side_box,
        }

    # ------------------------------------------------------------------
    def _op_key(self) -> str:
        return OP_KEY.get(self.operation.get(), "concat")

    def _apply_container_default(self, op: str):
        """「保持原格式」在这两种操作下没有意义，替用户挑一个真能用的容器。

        多音轨必须 mkv（MP4 对多音轨与字幕支持差），所以直接锁住；
        在线 m3u8 录制默认 mkv：实测只有它在「还在写」和「被硬杀」两种情况下
        都打得开，mp4 的文件尾要等写完才存在。自动设的都在离开该操作时还原，
        用户自己动过的选择一律不覆盖。
        """
        if self._auto_container and self.container.get() != self._auto_container:
            self._auto_container = ""      # 用户已经改过，别再动他的选择
        if self._auto_container:
            self.container.set(CONTAINERS[0])
            self._auto_container = ""
        if op == "multitrack":
            self._auto_container = "mkv"
            self.container.set("mkv")
            self.container_cb.configure(state="disabled")
            return
        self.container_cb.configure(state="readonly")
        if op == "hls" and self._remote_target() and self.container.get() == CONTAINERS[0]:
            self._auto_container = "mkv"
            self.container.set("mkv")

    def _on_operation(self):
        for box in self._boxes.values():
            box.grid_remove()
        op = self._op_key()
        self._boxes[op].grid()
        self._apply_container_default(op)
        # m3u8 合成只用列表里的第一个文件（在线地址更是只有一个源），
        # 摆「将按此顺序处理全部文件」会误导
        if op in ("hls", "multitrack"):
            self.order_holder.grid_remove()
        else:
            self.order_holder.grid()
        self._on_join_mode()
        self._on_hls_mode()
        self.notify_output_changed()

    def _on_join_mode(self):
        if self.join_mode.get() == "reencode":
            self.rec_box.grid()
        else:
            self.rec_box.grid_remove()
        self._on_transition()

    def _on_hls_mode(self):
        if self.hls_mode.get() == "reencode":
            self.hls_rec_box.grid()
        else:
            self.hls_rec_box.grid_remove()
        self._update_hls_tip()

    # ---------------- m3u8：在线地址 / 录制 ----------------
    BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36 Edg/156.0.0.0")

    def _remote_target(self) -> str:
        """在线地址（去首尾空格）；没填返回空串。"""
        return self.hls_url.get().strip()

    @property
    def src_override(self):
        return self._remote_target() or None

    @property
    def src_is_remote(self) -> bool:
        return bool(self._remote_target())

    def _headers(self) -> tuple[str, str]:
        return (self.hls_ua.get().strip(), self.hls_refer.get().strip())

    def _reconnect_delay(self):
        """重连退避上限（秒）；返回 None 表示用户填的不是合法数字。"""
        return probe.reconnect_delay_seconds(self.hls_reconnect.get())

    def _on_url_changed(self):
        """地址一填，容器和落点就得跟着变——这才是「所见即所存」。"""
        if self._op_key() != "hls":
            return
        self._apply_container_default("hls")
        self._update_hls_tip()
        self.notify_output_changed()

    def _record_seconds(self) -> float:
        """录制时长上限。0 = 留空（一直录到手动停止），-1 = 填了但不是正数。"""
        text = self.hls_record.get().strip()
        if not text:
            return 0.0
        try:
            value = float(text)
        except ValueError:
            return -1.0
        return value if value > 0 else -1.0

    def _use_browser_ua(self):
        self.hls_ua.set(self.BROWSER_UA)
        self._update_hls_tip()

    def _hls_info(self, src: str):
        """带防盗链头去探测源，拿点播总时长与帧数（在线/本地列表都走这里）。"""
        ua, refer = self._headers()
        args = probe.hls_input_args(src, ua, refer, self._reconnect_delay())
        if not args:
            return self.app.get_info(src)
        key = (src, tuple(args))
        if key not in self._hls_info_cache:
            if len(self._hls_info_cache) > 8:      # 只是个小缓存，别让它无限长
                self._hls_info_cache.clear()
            try:
                self._hls_info_cache[key] = probe.probe(self.app.ffprobe_path, src,
                                                        input_args=args)
            except Exception:
                self._hls_info_cache[key] = None
        return self._hls_info_cache[key]

    def _hls_frames(self, src: str) -> int:
        """进度按帧算时要有帧数；时长未知的直播返回 0（退回滚动动画）。"""
        total = self.expected_duration(src)
        if not total:
            return 0
        info = self._hls_info(src)
        if info and info.video_frames and abs(total - float(info.duration or 0)) < 0.51:
            return info.video_frames          # 就是源本身（点播）
        fps = info.video.fps if info and info.video else 0
        return self.frames_from_fps(total, fps) if fps else 0

    def _update_hls_tip(self):
        """把「能不能边下边播、什么时候会真的结束」这件事说在前面。"""
        if not hasattr(self, "hls_tip"):
            return
        if self._op_key() != "hls":
            self.hls_tip.configure(text="", foreground=theme.MUTED)
            self.hls_tip.grid_remove()
            return
        self.hls_tip.grid()
        if not self._remote_target():
            self.hls_tip.configure(text="", foreground=theme.MUTED)
            return
        secs = self._record_seconds()
        ext = self.output_ext()
        if secs > 0:
            self.hls_tip.configure(
                text=f"下载约 {secs:g} 秒后自动结束，进度条按这个时长算百分比。",
                foreground=theme.MUTED)
        elif ext in ("mp4", "mov", "m4v"):
            self.hls_tip.configure(
                text="未填录制时长＝随时可能停，所以不显示百分比（进度条滚动，"
                     "状态栏显示已用时 / 速度 / 已写入大小）。"
                     "此刻输出是 mp4：mp4 的文件尾（moov）要等写完才存在，"
                     "录制中途打不开（实测 moov atom not found），想边下边播请改选 mkv；"
                     "点「停止」会让 ffmpeg 收尾，之后 mp4 也是完整可播的。",
                foreground=theme.WARN)
        else:
            self.hls_tip.configure(
                text=f"未填录制时长＝随时可能停，不显示百分比（进度条滚动，状态栏显示已用时 / "
                     f"速度 / 已写入大小）。输出 {ext} 支持边下边播：还在写就能打开看已下载的部分；"
                     "点播整片想要百分比，可把列表总时长填进「录制时长」。",
                foreground=theme.MUTED)

    def _on_transition(self):
        if self.join_mode.get() == "reencode" and self.transition_on.get():
            self.trans_row.grid()
        else:
            self.trans_row.grid_remove()

    # ------------------------------------------------------------------
    def _pick_audio(self):
        files = widgets.ask_open_files(self, widgets.AUDIO_TYPES, multiple=False)
        if files:
            self.audio_file.set(files[0])

    def _pick_side(self):
        files = widgets.ask_open_files(self, widgets.MEDIA_TYPES, multiple=False)
        if files:
            self.side_file.set(files[0])

    def on_src_changed(self):
        values = []
        for enc in ("libx264", "libx265", "libsvtav1", "h264_nvenc", "hevc_nvenc",
                    "h264_qsv", "h264_amf"):
            if enc in self.app.encoders:
                values.append(enc)
        # 「兼容拼接」和「m3u8 兼容合成」各有一行编码选择，绑的是同一组变量，
        # 所以要全部刷新，只留一个引用会让另一个停在旧列表上。
        if values and self._venc_cbs:
            for cb in self._venc_cbs:
                cb.configure(values=values)
            if self.venc.get() not in values:
                self.venc.set(values[0])
        self._refresh_order()

    def _refresh_order(self):
        lines = [f"{i:>2}. {path}" for i, path in enumerate(self.app.src_files, 1)]
        if not lines:
            lines = ["（尚未选择文件，请在主界面添加）"]
        self.order_text.configure(state="normal")
        self.order_text.delete("1.0", "end")
        self.order_text.insert("1.0", "\n".join(lines))
        self.order_text.configure(state="disabled")

    # ------------------------------------------------------------------
    @property
    def batch_exclusive(self) -> bool:
        return True

    def output_ext(self) -> str:
        v = self.container.get()
        if v == "保持原格式":
            if self._op_key() == "hls" and self._remote_target():
                # 在线列表没有「原格式」可言；直播录制选 mkv 最稳：
                # 实测它支持边下边播，硬杀也只是「提前结束」，mp4 会整段报废
                return "mkv"
            ext = self.app.src_ext() or "mp4"
            # m3u8 是播放列表不是容器，「保持原格式」对它没有意义
            return "mp4" if ext in ("m3u8", "m3u") else ext
        return v

    def output_suffix(self) -> str:
        return {"concat": "_merged", "hls": "_merged", "mux": "_muxed",
                "multitrack": "_multitrack", "side": "_sidebyside"}[self._op_key()]

    def expected_duration(self, src: str) -> float | None:
        """拼接后总时长 = 各段之和（减去转场重叠），否则进度条百分比会算错。"""
        if self._op_key() == "hls":
            secs = self._record_seconds()
            if secs > 0:
                return secs
            if is_http_url(src):
                # 在线直播不填时长就是「随时会停」，报个百分比反而像卡住了：
                # 这时进度条走滚动动画，状态栏显示已用时 / 速度 / 已写入大小
                return None
            if not probe.playlist_report(src)["has_endlist"]:
                return None
            return super().expected_duration(src)
        if self._op_key() != "concat":
            return super().expected_duration(src)
        sources = list(self.app.src_files) or [src]
        total = 0.0
        for p in sources:
            d = self._duration(p)
            if d <= 0:
                return None
            total += d
        if self.join_mode.get() == "reencode" and self.transition_on.get():
            try:
                trans = float(self.transition_dur.get())
            except ValueError:
                trans = 0.0
            total -= trans * max(0, len(sources) - 1)
        return total if total > 0 else None

    def expected_frames(self, src: str) -> int:
        """拼接后的总帧数 = 各段帧数之和（转场模式近似按时长比例折减）。"""
        if self._op_key() == "hls":
            return self._hls_frames(src)
        if self._op_key() != "concat":
            return super().expected_frames(src)
        sources = list(self.app.src_files) or [src]
        total = 0
        for p in sources:
            info = self.app.get_info(p)
            n = info.video_frames if info else 0
            if n <= 0:
                return 0
            total += n
        if total > 0 and self.join_mode.get() == "reencode" and self.transition_on.get():
            dur_all = self.expected_duration(src) or 0
            if dur_all > 0:
                src_all = 0.0
                for p in sources:
                    info = self.app.get_info(p)
                    src_all += info.duration if info else 0.0
                if src_all > 0:
                    total = int(round(total * dur_all / src_all))
        # 重新编码且统一了帧率时，实际总帧数 = 输出时长 × 目标帧率
        if self.join_mode.get() == "reencode":
            fps = self._target_fps(self.app.get_info(sources[0]) if sources else None)
            if fps:
                n = self.frames_from_fps(self.expected_duration(src), fps)
                if n > 0:
                    total = n
        return total

    def aux_files(self) -> list[str]:
        return list(self._aux_files)

    def cleanup(self):
        for path in list(self._aux_files) + sorted(self._list_paths):
            try:
                os.remove(path)
            except OSError:
                pass
        self._aux_files = []
        self._list_paths.clear()
        self._list_content = ""

    # ------------------------------------------------------------------
    def validate(self):
        op = self._op_key()
        if op == "concat":
            if len(self.app.src_files) < 2:
                return "首尾拼接至少需要 2 个文件，请在主界面添加。"
            if self.join_mode.get() == "reencode" and self.transition_on.get():
                try:
                    dur = float(self.transition_dur.get())
                except ValueError:
                    return "转场时长需要填写数字。"
                if dur <= 0:
                    return "转场时长必须大于 0。"
                durations = [self._duration(p) for p in self.app.src_files]
                if any(d <= 0 for d in durations):
                    return "无法读取全部片段的时长，不能使用转场，请改用直接拼接或不加转场。"
                shortest = min(durations)
                if dur >= shortest:
                    return f"转场时长必须小于最短片段的长度（{shortest:.2f} 秒）。"
        elif op == "hls":
            secs = self._record_seconds()
            if secs < 0:
                return "录制时长要填正数（秒），或留空表示一直录到点「停止」。"
            url = self._remote_target()
            if url:
                if self._reconnect_delay() is None:
                    return (f"重连等待要填 1–{probe.HLS_RECONNECT_MAX} 之间的秒数，"
                            f"留空则按默认 {probe.HLS_RECONNECT_DEFAULT} 秒。")
                if not is_http_url(url):
                    return (f"在线地址只支持 http:// 或 https://，当前是：{url}\n"
                            "（其它前缀不能交给 ffmpeg 打开）")
                if not probe.is_hls_playlist(url):
                    return ("在线地址里要能看出播放列表扩展名（.m3u8 / .m3u），"
                            f"查询参数不算。当前是：{url}")
                return None
            files = self.app.src_files
            if not files:
                return ("请在主界面选择 .m3u8 播放列表文件，"
                        "或在上方的「在线地址」里填 http(s) 播放列表。")
            playlist = files[0]
            if not probe.is_hls_playlist(playlist):
                return (f"第一个文件不是 m3u8 播放列表：{os.path.basename(playlist)}\n"
                        "请把 .m3u8 放在文件列表第一位；"
                        "如果只有一堆 .ts 分片没有列表，请改用「首尾拼接」。")
            if not os.path.isfile(playlist):
                return f"播放列表不存在：{playlist}"
            rep = probe.playlist_report(playlist)
            if rep["error"]:
                return rep["error"]
            if not (rep["segments"] or rep["variants"]):
                return "播放列表里没有分片（可能还没下载完，或者它不是媒体播放列表）。"
            if rep["missing"]:
                names = "、".join(os.path.basename(p) for p in rep["missing"])
                more = (f" 等 {rep['missing_total']} 个文件"
                        if rep["missing_total"] > len(rep["missing"]) else "")
                return (f"播放列表引用的文件找不到：{names}{more}\n"
                        "分片和加密密钥都必须与 .m3u8 放在同一个目录里才能合成。")
        elif op == "mux":
            if not self.app.src_files:
                return "请先在主界面选择提供画面的视频文件。"
            p = self.audio_file.get().strip()
            if not p:
                return "请选择提供声音的音频文件。"
            if not os.path.isfile(p):
                return f"音频文件不存在：{p}"
        elif op == "multitrack":
            if not self.app.src_files:
                return "请先在主界面选择主文件。"
            if not self.extra_list.files():
                return "请至少添加一个附加音轨 / 字幕文件。"
        elif op == "side":
            if not self.app.src_files:
                return "请先在主界面选择第一路视频。"
            p = self.side_file.get().strip()
            if not p:
                return "请选择第二路视频。"
            if not os.path.isfile(p):
                return f"文件不存在：{p}"
        return None

    # ------------------------------------------------------------------
    def build_cmd(self, src: str, dst: str) -> list[str]:
        op = self._op_key()
        if op == "concat":
            return self._build_concat(src, dst)
        if op == "hls":
            return self._build_hls(src, dst)
        if op == "mux":
            return self._build_mux(src, dst)
        if op == "multitrack":
            return self._build_multitrack(src, dst)
        return self._build_side(src, dst)

    # ============================================================== 首尾拼接
    def _sources(self):
        return list(self.app.src_files)

    def _build_concat(self, src: str, dst: str) -> list[str]:
        sources = self._sources() or [src]
        if self.join_mode.get() == "copy":
            return self._concat_copy(sources, dst)
        return self._concat_reencode(sources, dst)

    def _concat_copy(self, sources, dst) -> list[str]:
        list_path = self._concat_list_file(sources, dst)
        self._aux_files = [list_path]
        args = ["-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy"]
        if self.output_ext() in ("mp4", "mov"):
            args += ["-movflags", "+faststart"]
        return args + [dst]

    def _concat_list_file(self, sources, dst) -> str:
        """生成 concat 分离器需要的文件清单。

        ffmpeg 的 concat 分离器必须从文件读取清单，所以这里落地一个小文件，
        但放在**程序目录下的 temp/**（不是 C 盘临时目录），运行结束即删除，
        文件名由输出文件决定、不会每次刷新都变。
        """
        stem = os.path.splitext(os.path.basename(dst))[0] or "concat"
        stem = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", stem)[:48] or "concat"
        path = os.path.join(local_temp_dir(), f"concat_{stem}.txt")
        self._list_paths.add(path)

        lines = []
        for p in sources:
            safe = os.path.abspath(p).replace("\\", "/").replace("'", r"'\''")
            lines.append(f"file '{safe}'")
        content = "\n".join(lines) + "\n"
        if content != self._list_content or not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            self._list_content = content
        return path

    def _concat_reencode(self, sources, dst) -> list[str]:
        infos = [self.app.get_info(p) for p in sources]
        first = infos[0]
        width, height = self._target_size(first)
        fps = self._target_fps(first)
        has_audio = all(i and i.has_audio for i in infos)
        sr, layout = self._audio_format(first)

        args: list[str] = []
        for p in sources:
            args += ["-i", p]

        parts = []
        for i in range(len(sources)):
            vf = ["setpts=PTS-STARTPTS"]
            if width and height:
                vf.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos")
                vf.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black")
            else:
                vf.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
            if fps:
                vf.append(f"fps={fps}")
            vf += ["setsar=1", "format=yuv420p"]
            parts.append(f"[{i}:v]{','.join(vf)}[v{i}]")
            if has_audio:
                parts.append(
                    f"[{i}:a]aresample={sr}:async=1:first_pts=0,"
                    f"aformat=sample_fmts=fltp:sample_rates={sr}:channel_layouts={layout},"
                    f"asetpts=PTS-STARTPTS[a{i}]")

        if self.transition_on.get() and len(sources) > 1:
            graph, vout, aout = self._transition_graph(parts, infos, has_audio)
        else:
            refs = "".join(f"[v{i}]" + (f"[a{i}]" if has_audio else "") for i in range(len(sources)))
            graph = ";".join(parts)
            graph += f";{refs}concat=n={len(sources)}:v=1:a={1 if has_audio else 0}[vout]"
            if has_audio:
                graph += "[aout]"
            vout, aout = "vout", ("aout" if has_audio else None)

        args += ["-filter_complex", graph, "-map", f"[{vout}]"]
        if aout:
            args += ["-map", f"[{aout}]"]
        args += self._video_encode_args()
        if aout:
            args += self._audio_encode_args()
        else:
            args += ["-an"]
        if self.output_ext() in ("mp4", "mov"):
            args += ["-movflags", "+faststart"]
        return args + [dst]

    def _transition_graph(self, parts, infos, has_audio):
        """构造 xfade / acrossfade 串联滤镜图，返回 (graph, 视频标签, 音频标签)。"""
        try:
            dur = float(self.transition_dur.get())
        except ValueError:
            dur = 1.0
        dur = max(0.05, dur)
        trans = self.transition.get()
        durations = [(i.duration if i and i.duration else 0.0) for i in infos]

        graph_parts = list(parts)
        vcur, acc = "v0", durations[0]
        for k in range(1, len(infos)):
            offset = max(0.0, acc - dur)
            out = f"vx{k}"
            graph_parts.append(
                f"[{vcur}][v{k}]xfade=transition={trans}:duration={dur:.3f}:"
                f"offset={offset:.3f}[{out}]")
            acc = offset + max(durations[k], dur)
            vcur = out

        acur = None
        if has_audio:
            acur = "a0"
            for k in range(1, len(infos)):
                out = f"ax{k}"
                graph_parts.append(f"[{acur}][a{k}]acrossfade=d={dur:.3f}:c1=tri:c2=tri[{out}]")
                acur = out
        return ";".join(graph_parts), vcur, acur

    def _target_size(self, first):
        for label, w, h in RESOLUTIONS:
            if label == self.resolution.get():
                if w and h:
                    return w, h
                break
        if first and first.video and first.video.width:
            return (first.video.width - first.video.width % 2,
                    first.video.height - first.video.height % 2)
        return 0, 0

    def _target_fps(self, first):
        v = self.fps.get()
        if v == "保持各自帧率":
            return None
        if v == "跟随第一个视频":
            if first and first.video and first.video.fps:
                return f"{first.video.fps:.4f}".rstrip("0").rstrip(".")
            return None
        return v

    @staticmethod
    def _audio_format(first):
        sr, layout = 48000, "stereo"
        if first and first.audio:
            if first.audio.sample_rate:
                sr = first.audio.sample_rate
            if first.audio.channel_layout:
                layout = first.audio.channel_layout
            elif first.audio.channels == 1:
                layout = "mono"
        return sr, layout

    def _video_encode_args(self) -> list[str]:
        try:
            crf = int(float(self.crf.get()))
        except ValueError:
            crf = 20
        return builder.video_encode_args(self.venc.get(), crf=crf,
                                         preset=self.preset.get(), pix_fmt="yuv420p")

    def _audio_encode_args(self) -> list[str]:
        return builder.audio_encode_args(self.aenc.get(), bitrate=self.abr.get().strip() or None)

    def _duration(self, path) -> float:
        info = self.app.get_info(path)
        return float(info.duration) if info and info.duration else 0.0

    # ============================================================== m3u8 合成
    def _build_hls(self, src: str, dst: str) -> list[str]:
        """把播放列表指向的分片合成成一个普通视频文件（本地列表或在线地址）。

        输入参数必须排在 ``-i`` 之前才作用到这个输入上。
        复制流时不要手动加 ``-bsf:a aac_adtstoasc``：ffmpeg 会为 MP4 自动补，
        而音频不是 AAC（mp3 / ac3）的列表写了它反而打不开输出文件。
        """
        ua, refer = self._headers()
        args = probe.hls_input_args(src, ua, refer, self._reconnect_delay()) + ["-i", src]
        secs = self._record_seconds()
        if secs > 0:
            args += ["-t", f"{secs:g}"]        # 录制上限：到点自己停，进度条也按它算
        if self.hls_mode.get() == "reencode":
            args += self._video_encode_args() + self._audio_encode_args()
        else:
            args += ["-c", "copy"]
        if self.output_ext() in ("mp4", "mov"):
            args += ["-movflags", "+faststart"]
        return args + [dst]

    # ========================================================== 音视频合并
    def _build_mux(self, src: str, dst: str) -> list[str]:
        audio = self.audio_file.get().strip()
        args = ["-i", src, "-i", audio, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy"]
        enc = self.mux_aenc.get()
        if enc == "copy":
            args += ["-c:a", "copy"]
        else:
            args += builder.audio_encode_args(enc, bitrate=self.mux_abr.get().strip() or None)
        if self.mux_shortest.get():
            args += ["-shortest"]
        if self.output_ext() in ("mp4", "mov"):
            args += ["-movflags", "+faststart"]
        return args + [dst]

    # ========================================================== 多音轨封装
    def _build_multitrack(self, src: str, dst: str) -> list[str]:
        extras = self.extra_list.files()
        args = ["-i", src]
        for p in extras:
            args += ["-i", p]
        args += ["-map", "0"]
        for i in range(1, len(extras) + 1):
            # 界面上写的是「所有音轨与字幕都会复制进来」，字幕确实也得映射，
            # 否则附加文件的 .srt/.ass 会被静默丢掉。
            args += ["-map", f"{i}:a?", "-map", f"{i}:s?"]
        args += ["-c", "copy", "-map_metadata", "0"]
        args += builder.subtitle_codec_args(self.subtitle_codecs(src, *extras),
                                            self.output_ext())
        if dst.lower().endswith(".mp4"):
            args += ["-movflags", "+faststart"]
        return args + [dst]

    # ========================================================== 并排同屏
    def _build_side(self, src: str, dst: str) -> list[str]:
        second = self.side_file.get().strip()
        layout = self.side_layout.get()
        size = self._side_size(src, layout)

        dim = f"scale=-2:{size}" if layout == "hstack" else f"scale={size}:-2"
        graph = (f"[0:v]{dim},setsar=1,format=yuv420p[a];"
                 f"[1:v]{dim},setsar=1,format=yuv420p[b];"
                 f"[a][b]{layout}=inputs=2[v]")

        mode = self.side_audio.get()
        args = ["-i", src, "-i", second]
        if mode == "mix":
            graph += f";[0:a][1:a]{self.amix_args(2, 'longest')}[aout]"
            args += ["-filter_complex", graph, "-map", "[v]", "-map", "[aout]",
                     "-c:a", "aac", "-b:a", "192k"]
        else:
            args += ["-filter_complex", graph, "-map", "[v]"]
            if mode == "none":
                args += ["-an"]
            else:
                args += ["-map", "0:a?", "-c:a", "copy"]
        args += self._video_encode_args()
        if self.output_ext() in ("mp4", "mov"):
            args += ["-movflags", "+faststart"]
        return args + [dst]

    def _side_size(self, src: str, layout: str) -> int:
        for label, w, h in RESOLUTIONS:
            if label == self.side_size.get():
                if w and h:
                    size = h if layout == "hstack" else w
                    return size - size % 2
                break
        info = self.app.get_info(src)
        size = 0
        if info and info.video:
            size = info.video.height if layout == "hstack" else info.video.width
        size = max(2, int(size or 720))
        return size - size % 2
