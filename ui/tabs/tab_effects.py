# -*- coding: utf-8 -*-
"""特效 / 叠加页：变速、调色、水印、字幕、画中画。"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk

from core import builder
from core.util import escape_filter_path, filter_unsafe_chars, local_temp_dir
from .. import widgets
from .base import BaseTab
from .subform import SubForm as _SubForm

OPERATIONS = [
    ("none", "仅调整画面（调色 / 模糊 / 锐化）"),
    ("speed", "变速（快放 / 慢放，声音同步变调不变）"),
    ("text_wm", "文字水印"),
    ("image_wm", "图片水印 / Logo"),
    ("pip", "画中画（视频叠加视频）"),
    ("burn_sub", "烧录字幕（硬字幕，永久显示）"),
    ("soft_sub", "封装字幕（软字幕，可开关）"),
]
OP_KEY = {label: key for key, label in OPERATIONS}
OP_LABEL = {key: label for key, label in OPERATIONS}

POSITIONS = ["左上", "上中", "右上", "左中", "正中", "右中", "左下", "下中", "右下"]
TEXT_COLORS = ["white", "black", "yellow", "red", "green", "blue", "orange", "#00c8ff"]

# 变速时的音频处理方式：(键, 说明)
SPEED_AUDIO_MODES = [
    ("sync", "同步变速（保持音调）"),
    ("keep", "保留原音频（会不同步）"),
    ("none", "丢弃音频（静音）"),
]


class EffectsTab(BaseTab):
    name = "特效 / 叠加"
    hint = ("给视频加水印、字幕、变速、调色、画中画。"
            "需要把多个视频接成一段、合并音轨或并排同屏，请使用左侧「合并 / 拼接」功能页。")
    accept = "video"
    suffix = "_effect"

    # ------------------------------------------------------------------
    def build(self):
        self._aux_files: list[str] = []
        self._text_cache: dict[int, str] = {}
        # 本页面写到 temp/ 下的所有文本文件：行数改少后旧文件不能再留着，
        # 否则 cleanup 只删当前引用的那几个，剩下的要等下次启动才被回收。
        self._created_files: set[str] = set()
        f = self.form

        self.operation = tk.StringVar(value=OP_LABEL["none"])
        self.logo_file = tk.StringVar(value="")
        self.sub_file = tk.StringVar(value="")

        # 变速
        self.speed = tk.StringVar(value="2.0")
        self.audio_mode = tk.StringVar(value="sync")

        # 水印
        self.wm_text = tk.StringVar(value="示例水印")
        self.wm_size = tk.StringVar(value="32")
        self.wm_color = tk.StringVar(value="white")
        self.wm_pos = tk.StringVar(value="右下")
        self.wm_margin = tk.StringVar(value="20")
        self.wm_opacity = tk.StringVar(value="0.85")
        self.wm_box = tk.BooleanVar(value=True)
        self.wm_scale_mode = tk.StringVar(value="percent")
        self.wm_width = tk.StringVar(value="18")
        self.overlay_pos = tk.StringVar(value="右下")
        self.overlay_margin = tk.StringVar(value="20")

        # 调色
        self.brightness = tk.DoubleVar(value=0.0)
        self.contrast = tk.DoubleVar(value=1.0)
        self.saturation = tk.DoubleVar(value=1.0)
        self.gamma = tk.DoubleVar(value=1.0)
        self.blur = tk.DoubleVar(value=0.0)
        self.sharpen = tk.DoubleVar(value=0.0)

        # 编码
        self.venc = tk.StringVar(value="libx264")
        self.crf = tk.StringVar(value="18")
        self.preset = tk.StringVar(value="veryfast")

        f.section("操作类型")
        self.op_cb = f.combo("", self.operation, [label for _k, label in OPERATIONS],
                             width=44, on_change=self._on_operation)

        self.op_box = ttk.Frame(self.form_holder, style="Panel.TFrame")
        self.op_box.grid(row=f.row, column=0, columnspan=2, sticky="ew")
        self.op_box.columnconfigure(1, weight=1)
        f.row += 1

        self._build_boxes()

        f.section("画面调整（所有操作均可用，保持默认值表示不改变画面）")
        f.fscale("亮度", self.brightness, -1.0, 1.0)
        f.fscale("对比度", self.contrast, 0.0, 3.0)
        f.fscale("饱和度", self.saturation, 0.0, 3.0)
        f.fscale("伽马", self.gamma, 0.1, 3.0)
        f.fscale("模糊", self.blur, 0.0, 20.0, unit="σ")
        f.fscale("锐化", self.sharpen, 0.0, 3.0)

        f.section("输出编码（需要重新编码时生效）")
        self.venc_cb = f.combo("视频编码", self.venc, ["libx264"], width=30)
        f.entry("CRF 画质", self.crf, width=8)
        f.combo("编码速度", self.preset, builder.PRESETS, width=16)

        self._on_operation()

    # ------------------------------------------------------------------
    def _new_box(self):
        box = ttk.Frame(self.op_box, style="Panel.TFrame")
        box.grid(row=0, column=1, sticky="ew")
        box.columnconfigure(1, weight=1)
        return box

    def _build_boxes(self):
        # --- 变速 ---
        self.speed_box = self._new_box()
        g = _SubForm(self.speed_box)
        g.field_hint("速度倍率", self.speed, "倍", "2 = 两倍速快放，0.5 = 慢放一半")
        g.radio_row("音频处理", self.audio_mode, SPEED_AUDIO_MODES)
        g.note("① 同步变速：用 atempo 同步处理音频，音调不变、声画保持一致（推荐）。\n"
               "② 保留原音频：只变速画面，音频原样复制，结果会声画不同步。\n"
               "③ 丢弃音频：输出无声视频。")

        # --- 文字水印 ---
        self.text_wm_box = self._new_box()
        g = _SubForm(self.text_wm_box)
        g.entry("水印文字", self.wm_text)
        g.pair("字号 / 颜色", self.wm_size, "px", self.wm_color, TEXT_COLORS, combo_width=10)
        g.combo("位置", self.wm_pos, POSITIONS, width=10)
        g.pair("边距 / 不透明度", self.wm_margin, "px", self.wm_opacity, None)
        g.check("", self.wm_box, "加半透明底衬（提高可读性）")

        # --- 图片水印 ---
        self.img_wm_box = self._new_box()
        g = _SubForm(self.img_wm_box)
        g.file_row("图片文件", self.logo_file, self._pick_logo, widgets.IMAGE_TYPES)
        g.combo("宽度单位", self.wm_scale_mode, ["percent", "px"], width=10)
        g.field_hint("水印宽度", self.wm_width, "", "percent = 占主视频宽度百分比，px = 固定像素")
        g.combo("位置", self.wm_pos, POSITIONS, width=10)
        g.field_hint("边距", self.wm_margin, "px", "")

        # --- 画中画 ---
        self.pip_box = self._new_box()
        g = _SubForm(self.pip_box)
        g.file_row("叠加视频", self.logo_file, self._pick_logo, widgets.MEDIA_TYPES,
                   hint="将作为小窗叠加在主视频上")
        g.field_hint("小窗宽度", self.wm_width, "% 主视频宽度", "")
        g.combo("位置", self.overlay_pos, POSITIONS, width=10)
        g.field_hint("边距", self.overlay_margin, "px", "")

        # --- 字幕 ---
        self.sub_box = self._new_box()
        g = _SubForm(self.sub_box)
        g.file_row("字幕文件", self.sub_file, self._pick_sub, widgets.SUB_TYPES)
        g.note("支持 .srt / .ass / .ssa / .vtt。硬字幕会永久烙进画面；"
               "软字幕建议输出 MKV（输出 MP4 时转为 mov_text，兼容性一般）。")

        self._all_boxes = {
            "speed": self.speed_box,
            "text_wm": self.text_wm_box,
            "image_wm": self.img_wm_box,
            "pip": self.pip_box,
            "burn_sub": self.sub_box,
            "soft_sub": self.sub_box,
        }

    # ------------------------------------------------------------------
    def _op_key(self) -> str:
        return OP_KEY.get(self.operation.get(), "none")

    def _on_operation(self):
        for box in set(self._all_boxes.values()):
            box.grid_remove()
        box = self._all_boxes.get(self._op_key())
        if box is not None:
            box.grid()
        self.notify_output_changed()

    def _pick_logo(self):
        files = widgets.ask_open_files(self, widgets.MEDIA_TYPES, multiple=False)
        if files:
            self.logo_file.set(files[0])

    def _pick_sub(self):
        files = widgets.ask_open_files(self, widgets.SUB_TYPES, multiple=False)
        if files:
            self.sub_file.set(files[0])

    def on_src_changed(self):
        values = []
        for enc in ("libx264", "libx265", "libsvtav1", "h264_nvenc", "hevc_nvenc",
                    "h264_qsv", "h264_amf"):
            if enc in self.app.encoders:
                values.append(enc)
        if values:
            self.venc_cb.configure(values=values)
            if self.venc.get() not in values:
                self.venc.set(values[0])

    def output_suffix(self) -> str:
        return {"speed": "_speed", "text_wm": "_wm", "image_wm": "_wm",
                "pip": "_pip", "burn_sub": "_sub",
                "soft_sub": "_sub"}.get(self._op_key(), "_effect")

    # -- 进度预估 ---------------------------------------------------------
    def _speed_factor(self) -> float:
        """变速倍率；无效或非正返回 0（表示不可用）。"""
        if self._op_key() != "speed":
            return 0.0
        return self._positive_float(self.speed.get())

    def expected_duration(self, src: str) -> float | None:
        """变速会改变输出时长：2 倍速 → 时长减半。"""
        base = super().expected_duration(src)
        factor = self._speed_factor()
        if factor <= 0 or not base:
            return base
        return base / factor

    def expected_frames(self, src: str) -> int:
        """变速不改变帧率，总帧数 = 原帧数 / 倍率。"""
        factor = self._speed_factor()
        if factor <= 0:
            return super().expected_frames(src)
        n = self.frames_from_duration(src, self.expected_duration(src))
        return n if n > 0 else super().expected_frames(src)

    def output_ext(self) -> str:
        return self.app.src_ext() or "mp4"

    def aux_files(self) -> list[str]:
        return list(self._aux_files)

    def cleanup(self):
        for path in set(self._aux_files) | self._created_files:
            try:
                os.remove(path)
            except OSError:
                pass
        self._aux_files = []
        self._created_files.clear()
        self._text_cache.clear()

    def _text_files(self, text: str) -> list[str]:
        """把水印文字按行写成文本文件，返回路径列表。

        ffmpeg 的 drawtext 用 textfile 读取文本可以完全绕开转义问题；
        但文件里若有换行符，ffmpeg 会把换行本身画成一个方块，
        所以这里**一行一个文件**。文件放在程序目录的 temp/ 下，运行结束即删。
        """
        lines = str(text).splitlines() or [""]
        folder = local_temp_dir()
        paths = []
        for i, line in enumerate(lines):
            path = os.path.join(folder, f"watermark_{os.getpid()}_{i}.txt")
            line = line if line.strip() else " "
            if self._text_cache.get(i) != line or not os.path.exists(path):
                with open(path, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(line)
                self._text_cache[i] = line
            self._created_files.add(path)
            paths.append(path)
        return paths

    # ------------------------------------------------------------------
    def _eq_chain(self) -> list[str]:
        chain, eq = [], []
        if abs(self.brightness.get()) > 1e-6:
            eq.append(f"brightness={self.brightness.get():.4f}")
        if abs(self.contrast.get() - 1.0) > 1e-6:
            eq.append(f"contrast={self.contrast.get():.4f}")
        if abs(self.saturation.get() - 1.0) > 1e-6:
            eq.append(f"saturation={self.saturation.get():.4f}")
        if abs(self.gamma.get() - 1.0) > 1e-6:
            eq.append(f"gamma={self.gamma.get():.4f}")
        if eq:
            chain.append("eq=" + ":".join(eq))
        if self.blur.get() > 0.01:
            chain.append(f"gblur=sigma={self.blur.get():.2f}")
        if self.sharpen.get() > 0.01:
            chain.append(f"unsharp=5:5:{self.sharpen.get():.2f}:5:5:0")
        return chain

    def _encode_args(self) -> list[str]:
        try:
            crf = int(float(self.crf.get()))
        except ValueError:
            crf = 18
        return builder.video_encode_args(self.venc.get(), crf=crf, preset=self.preset.get())

    def _reencode_tail(self, encode_audio: bool = False, drop_audio: bool = False) -> list[str]:
        """视频重编码 + 音频处理方式。

        音频怎么处理**完全由用户选项决定，不能用 ffprobe 的探测结果去推断**：
        探测可能还没返回、或者失败，据此注入 ``-an`` 会把音频静默丢掉，
        表现为「不管选哪个选项都没有声音」。源文件本来就没有音轨时，
        ffmpeg 会忽略音频参数自己处理，不会报错。
        """
        tail = self._encode_args()
        if drop_audio:
            tail += ["-an"]
        elif encode_audio:
            tail += ["-c:a", "aac", "-b:a", "192k"]
        else:
            tail += ["-c:a", "copy"]
        return tail

    # ------------------------------------------------------------------
    def _filter_path_problem(self, op: str) -> str | None:
        """嵌进滤镜图的路径无法包含单引号，提前用人话提示。

        ``fontfile`` / ``textfile`` / ``subtitles=filename`` 都是滤镜参数，
        而 ffmpeg 的滤镜引用本身就靠 ``'`` 成对，实测 ``\\'``、``''``、
        ``'\\''`` 三种写法都不能表示一个引号字符——路径里有 ``'`` 时
        文件名会被从引号处截断，报错还看不出来是路径的问题。
        作为输入文件（``-i``）传进去的图片 / 视频 / 字幕不受影响，无需检查。
        """
        if op == "text_wm":
            candidates = [local_temp_dir(), self.app.font_path]
        elif op == "burn_sub":
            candidates = [self.sub_file.get().strip()]
        else:
            return None
        for path in candidates:
            if path and filter_unsafe_chars(path):
                return (f"路径里含有单引号 ' ，ffmpeg 的滤镜参数无法转义它：\n{path}\n\n"
                        "请把文件（或本程序所在目录）改到不含单引号的路径再试。")
        return None

    def validate(self):
        op = self._op_key()
        problem = self._filter_path_problem(op)
        if problem:
            return problem
        if op in ("image_wm", "pip"):
            p = self.logo_file.get().strip()
            if not p:
                return "请选择要叠加的图片 / 视频文件。"
            if not os.path.isfile(p):
                return f"文件不存在：{p}"
        if op in ("burn_sub", "soft_sub"):
            p = self.sub_file.get().strip()
            if not p:
                return "请选择字幕文件。"
            if not os.path.isfile(p):
                return f"字幕文件不存在：{p}"
        if op == "speed":
            try:
                s = float(self.speed.get())
            except ValueError:
                return "速度倍率需要填写数字。"
            if not 0.05 <= s <= 100:
                return "速度倍率需在 0.05 ~ 100 之间。"
        return None

    # ------------------------------------------------------------------
    def build_cmd(self, src: str, dst: str) -> list[str]:
        op = self._op_key()
        eq = self._eq_chain()

        if op == "none":
            if not eq:
                return ["-i", src, "-c", "copy", dst]
            return ["-i", src, "-vf", ",".join(eq)] + self._reencode_tail() + [dst]

        if op == "speed":
            try:
                speed = float(self.speed.get())
            except ValueError:
                speed = 1.0
            vf = eq + [f"setpts={1.0 / speed:.6f}*PTS"]
            args = ["-i", src, "-vf", ",".join(vf)]
            mode = self.audio_mode.get()
            if mode == "sync":
                args += ["-af", builder.atempo_chain(speed)]
                args += self._reencode_tail(encode_audio=True)
            elif mode == "keep":
                args += self._reencode_tail(encode_audio=False)
            else:
                args += self._reencode_tail(drop_audio=True)
            return args + [dst]

        if op == "text_wm":
            files = self._text_files(self.wm_text.get())
            self._aux_files = list(files)
            pos = builder.overlay_position(self.wm_pos.get(), self._safe_int(self.wm_margin.get(), 20))
            x, y = pos.split(":")
            texts = builder.drawtext_lines(
                [escape_filter_path(p) for p in files],
                escape_filter_path(self.app.font_path) if self.app.font_path else "",
                size=self._safe_int(self.wm_size.get(), 32),
                color=self.wm_color.get(),
                border=2, border_color="black@0.6",
                x=x, y=y,
                alpha=self._safe_float(self.wm_opacity.get(), 0.85),
                box=self.wm_box.get(),
            )
            return ["-i", src, "-vf", ",".join(eq + texts)] + self._reencode_tail() + [dst]

        if op in ("image_wm", "pip"):
            media = self.logo_file.get().strip()
            args = ["-i", src, "-i", media]
            if op == "pip":
                pct = max(2, min(100, self._safe_int(self.wm_width.get(), 30))) / 100.0
                # 「小窗宽度」是相对**主视频**的百分比。写成 iw*pct 会按叠加素材
                # 自己的宽度缩放（1080p 的视频叠一张 200px 截图，40% 只有 80px），
                # 画面大小完全对不上界面说明。
                main_w = self.info.video.width if (self.info and self.info.video) else 0
                if main_w:
                    graph = f"[1:v]scale={max(16, int(main_w * pct) // 2 * 2)}:-2[ov]"
                else:
                    graph = f"[1:v]scale=iw*{pct:.4f}:-2[ov]"
                pos = builder.overlay_position(self.overlay_pos.get(),
                                               self._safe_int(self.overlay_margin.get(), 20))
                overlay_opts = f"{pos}:shortest=1"
            else:
                graph = f"[1:v]scale={self._resolve_logo_width()}:-1[ov]"
                pos = builder.overlay_position(self.wm_pos.get(),
                                               self._safe_int(self.wm_margin.get(), 20))
                overlay_opts = pos
            if eq:
                graph += f";[0:v]{','.join(eq)}[base];[base][ov]overlay={overlay_opts}[v]"
            else:
                graph += f";[0:v][ov]overlay={overlay_opts}[v]"
            args += ["-filter_complex", graph, "-map", "[v]"]
            # -map 0:a? 带问号表示「有音轨就带上」，无需依赖探测结果
            args += ["-map", "0:a?", "-c:a", "copy"]
            args += self._encode_args()
            return args + [dst]

        if op == "burn_sub":
            sub = escape_filter_path(self.sub_file.get().strip())
            vf = eq + [f"subtitles=filename='{sub}'"]
            return ["-i", src, "-vf", ",".join(vf)] + self._reencode_tail() + [dst]

        if op == "soft_sub":
            sub = self.sub_file.get().strip()
            container = self.output_ext()
            # 新增的字幕永远排在已有字幕之后，所以 -c:s 的序号顺序 = 源文件字幕 + 这个文件
            added = ("ass" if sub.lower().endswith((".ass", ".ssa")) else
                     "webvtt" if sub.lower().endswith(".vtt") else "srt")
            codecs = self.subtitle_codecs(src) + [added]
            args = ["-i", src, "-i", sub, "-map", "0", "-map", "1", "-c", "copy"]
            # 统一 -c:s srt 会把源文件里的 PGS 等图形字幕也强转成文本字幕而报错；
            # 按流逐个指定，能原样复制的一律不动。
            args += builder.subtitle_codec_args(codecs, container)
            if container in ("mp4", "mov", "m4v"):
                args += ["-movflags", "+faststart"]
            return args + [dst]

        return ["-i", src, "-c", "copy", dst]

    def _resolve_logo_width(self) -> int:
        raw = self._safe_int(self.wm_width.get(), 18)
        if self.wm_scale_mode.get() == "percent":
            main_w = self.info.video.width if (self.info and self.info.video) else 1920
            return max(16, int(main_w * raw / 100.0))
        return max(4, raw)

    @staticmethod
    def _safe_int(text, default: int) -> int:
        try:
            return int(float(str(text).strip()))
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _safe_float(text, default: float) -> float:
        try:
            return float(str(text).strip())
        except (ValueError, TypeError):
            return default

