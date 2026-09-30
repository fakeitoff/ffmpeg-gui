# -*- coding: utf-8 -*-
"""媒体信息页（只读，不执行转码）。"""
from __future__ import annotations

import json
import os
import tkinter as tk
from tkinter import filedialog, ttk

from core.util import human_bitrate, human_duration, human_size
from .base import BaseTab


class InfoTab(BaseTab):
    name = "媒体信息"
    hint = "查看当前源文件的容器、编码、分辨率、码率等详细信息，可导出为文本或 JSON。"
    accept = "any"
    runnable = False

    def build(self):
        f = self.form

        bar = f.full_row(pady=(4, 8))
        ttk.Button(bar, text="刷新", command=self.on_src_changed, width=8).pack(side="left")
        ttk.Button(bar, text="复制全部", command=self._copy, width=10).pack(side="left", padx=6)
        ttk.Button(bar, text="导出为 TXT…", command=self._export_txt, width=14).pack(side="left")
        ttk.Button(bar, text="导出为 JSON…", command=self._export_json, width=14).pack(side="left", padx=6)

        holder = f.full_row(pady=(0, 10), stretch=True)
        self.text = tk.Text(holder, height=24, wrap="none", bg="#fbfbfc", fg="#1f2329",
                            relief="solid", borderwidth=1, font=("Consolas", 10), padx=10, pady=8)
        self.text.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(holder, orient="vertical", command=self.text.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        hsb = ttk.Scrollbar(holder, orient="horizontal", command=self.text.xview)
        hsb.grid(row=1, column=0, sticky="ew")
        holder.rowconfigure(0, weight=1)
        self.text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.text.tag_configure("head", foreground="#2563eb", font=("Consolas", 10, "bold"))
        self.text.tag_configure("key", foreground="#6b7280")
        self.text.tag_configure("warn", foreground="#b91c1c")
        self._info = None

    # ------------------------------------------------------------------
    def on_src_changed(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self._info = self.app.info
        if not self._info:
            self.text.insert("end", "尚未选择文件，或该文件无法被 ffprobe 解析。\n", "warn")
            self.text.configure(state="disabled")
            return
        for line, tag in self._format(self._info):
            self.text.insert("end", line + "\n", tag or "")
        self.text.configure(state="disabled")

    @staticmethod
    def _format(info) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []

        def kv(key, value):
            rows.append((f"{key:<12}{value}", ""))

        rows.append(("═" * 78, "head"))
        rows.append((f"文件信息  {os.path.basename(info.path)}", "head"))
        rows.append(("═" * 78, "head"))
        kv("完整路径", info.path)
        kv("容器格式", f"{info.format_name}  {info.format_long}")
        kv("时长", f"{human_duration(info.duration)}  （{info.duration:.3f} 秒）")
        kv("文件大小", human_size(info.size))
        kv("总码率", human_bitrate(info.bit_rate))
        kv("流数量", str(info.nb_streams))
        for k, v in (info.tags or {}).items():
            if k.lower() in ("major_brand", "minor_version", "compatible_brands", "encoder"):
                kv(f"标签 {k}", str(v))

        for stream in info.streams:
            rows.append(("", ""))
            rows.append((f"── 流 #{stream.index}  [{stream.type_cn}] " + "─" * 40, "head"))
            kv("编码", f"{stream.codec}  {stream.profile}".strip())
            if stream.type == "video":
                ratio = ""
                if stream.width and stream.height:
                    from math import gcd

                    g = gcd(stream.width, stream.height)
                    ratio = f"  （{stream.width // g}:{stream.height // g}）"
                kv("分辨率", f"{stream.resolution}{ratio}")
                if stream.fps:
                    kv("帧率", f"{stream.fps:.4f} fps")
                kv("像素格式", stream.pix_fmt or "-")
            elif stream.type == "audio":
                kv("采样率", f"{stream.sample_rate} Hz" if stream.sample_rate else "-")
                kv("声道数", f"{stream.channels}  {stream.channel_layout}".strip())
                kv("采样格式", stream.raw.get("sample_fmt", "-"))
            kv("码率", human_bitrate(stream.bit_rate))
            if stream.lang:
                kv("语言", stream.lang)
            if stream.title:
                kv("标题", stream.title)
            disp = stream.raw.get("disposition") or {}
            flags = [k for k, v in disp.items() if v]
            if flags:
                kv("标记", ", ".join(flags))
        return rows

    # ------------------------------------------------------------------
    def _copy(self):
        if self.text.get("1.0", "end").strip():
            self.clipboard_clear()
            self.clipboard_append(self.text.get("1.0", "end").rstrip())

    def _export_txt(self):
        if not self._info:
            return
        path = filedialog.asksaveasfilename(
            title="导出媒体信息", defaultextension=".txt",
            initialfile=os.path.splitext(os.path.basename(self._info.path))[0] + "_info.txt",
            filetypes=[("文本文件", "*.txt")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.text.get("1.0", "end").rstrip() + "\n")
        self.app.log(f"媒体信息已导出：{path}", "ok")

    def _export_json(self):
        if not self._info:
            return
        path = filedialog.asksaveasfilename(
            title="导出媒体信息(JSON)", defaultextension=".json",
            initialfile=os.path.splitext(os.path.basename(self._info.path))[0] + "_info.json",
            filetypes=[("JSON 文件", "*.json")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self._info.raw, fh, ensure_ascii=False, indent=2)
        self.app.log(f"媒体信息已导出：{path}", "ok")
