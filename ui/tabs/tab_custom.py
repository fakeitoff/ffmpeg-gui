# -*- coding: utf-8 -*-
"""自定义命令页：直接手写 ffmpeg 参数。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from core.util import split_command, strip_global_args
from .base import BaseTab

TEMPLATE = """-i {input} -c:v libx264 -crf 20 -preset medium -c:a aac -b:a 192k {output}"""

SNIPPETS = [
    ("直接复制（重封装）", "-c copy"),
    ("仅视频重编码", "-c:v libx264 -crf 20 -preset medium -c:a copy"),
    ("仅音频重编码", "-c:v copy -c:a aac -b:a 192k"),
    ("缩放 1080p", '-vf "scale=1920:-2:flags=lanczos"'),
    ("限制帧率 30", "-r 30"),
    ("截取 10~20 秒", "-ss 00:00:10 -t 10"),
    ("生成 GIF", '-vf "fps=12,scale=480:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse" -loop 0'),
    ("提取音频 MP3", "-vn -c:a libmp3lame -b:a 192k"),
    ("去除音频", "-an -c:v copy"),
    ("调整音量 1.5 倍", '-af "volume=1.5"'),
    ("文字水印（右上角）", '-vf "drawtext=text=\'水印\':x=W-w-20:y=20:fontsize=32:fontcolor=white"'),
    ("硬件加速解码", "-hwaccel auto"),
    ("快速网络播放", "-movflags +faststart"),
    ("2 秒后开始", "-ss 2"),
    ("只输出前 30 秒", "-t 30"),
    ("元数据清空", "-map_metadata -1"),
]


class CustomTab(BaseTab):
    name = "自定义命令"
    hint = ("直接编写完整的 ffmpeg 参数，用 {input} 代表源文件、{output} 代表输出文件。"
            "下方「命令预览」会实时显示实际执行的完整命令。")
    accept = "any"
    suffix = "_custom"
    default_ext = "mp4"

    # ------------------------------------------------------------------
    def build(self):
        f = self.form

        # 所有行都通过 form 分配行号，不要手工 grid(row=N) ——
        # 否则很容易和 section 抢同一行，控件会叠在一起。
        bar = f.full_row(pady=(4, 6))
        ttk.Label(bar, text="插入：", style="Form.TLabel").pack(side="left")
        ttk.Button(bar, text="{input}", width=8,
                   command=lambda: self._insert("{input}")).pack(side="left", padx=(2, 4))
        ttk.Button(bar, text="{output}", width=9,
                   command=lambda: self._insert("{output}")).pack(side="left", padx=(0, 12))
        ttk.Button(bar, text="重置模板", width=10, command=self._reset).pack(side="left")

        holder = f.full_row(pady=(0, 10), stretch=True)
        self.text = tk.Text(holder, height=7, wrap="word", bg="#fbfbfc", fg="#1f2329",
                            relief="solid", borderwidth=1, font=("Consolas", 10), padx=10, pady=8,
                            insertbackground="#1f2329")
        self.text.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(holder, orient="vertical", command=self.text.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        holder.rowconfigure(0, weight=1)
        self.text.configure(yscrollcommand=vsb.set)
        self.text.insert("1.0", TEMPLATE)

        f.section("常用参数片段（点击插入到尾部）")
        frag = f.full_row(pady=(0, 10))
        col = 0
        row_i = 0
        for label, snippet in SNIPPETS:
            ttk.Button(frag, text=label, width=20,
                       command=lambda s=snippet: self._insert(s)).grid(
                row=row_i, column=col, padx=3, pady=3, sticky="w")
            col += 1
            if col >= 4:
                col = 0
                row_i += 1

        f.section("输出")
        self.ext = tk.StringVar(value="mp4")
        f.combo("输出扩展名", self.ext,
                ["mp4", "mkv", "mov", "avi", "webm", "mp3", "m4a", "wav", "flac", "gif", "jpg", "png"],
                width=12, on_change=self.notify_output_changed)
        f.note("提示：ffmpeg 会根据输出文件的扩展名自动选择合适的封装格式，"
               "所以扩展名要与命令中的编码参数匹配。")

    # ------------------------------------------------------------------
    def _insert(self, snippet: str):
        text = self.text
        try:
            text.insert("insert", (" " if snippet.startswith("-") else "") + snippet)
        except tk.TclError:
            text.insert("end", snippet)
        text.focus_set()

    def _reset(self):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", TEMPLATE)

    def output_ext(self) -> str:
        return self.ext.get()

    def _tokens(self):
        raw = self.text.get("1.0", "end").strip()
        tokens = strip_global_args(split_command(raw))
        if tokens and tokens[0].lower() in ("ffmpeg", "ffmpeg.exe"):
            tokens = tokens[1:]
        return tokens

    # ------------------------------------------------------------------
    def validate(self):
        raw = self.text.get("1.0", "end").strip()
        if not raw:
            return "命令内容为空。"
        if "{input}" not in raw:
            return "命令中缺少 {input} 占位符，无法确定源文件。"
        if "{output}" not in raw:
            return "命令中缺少 {output} 占位符，无法确定输出文件。"
        try:
            tokens = self._tokens()
        except ValueError as exc:
            return f"命令解析失败：{exc}"
        if len(tokens) < 2:
            return "命令过短，请补全参数。"
        return None

    def build_cmd(self, src: str, dst: str) -> list[str]:
        tokens = self._tokens()
        out = []
        for tok in tokens:
            tok = tok.replace("{input}", src).replace("{output}", dst)
            out.append(tok)
        return out
