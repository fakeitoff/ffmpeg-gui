# -*- coding: utf-8 -*-
"""ffmpeg / ffprobe 定位与媒体信息解析。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

from .util import popen_kwargs

# 常见安装位置（PATH 中找不到时兜底搜索）
_WIN_FALLBACKS = [
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"D:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    r"D:\ProgramFiles\ffmpeg\bin\ffmpeg.exe",
]
_WIN_GLOBS = [
    r"C:\ffmpeg*\**\bin\ffmpeg.exe",
    r"D:\**\ffmpeg*\**\bin\ffmpeg.exe",
    r"C:\Program Files\**\ffmpeg*\**\bin\ffmpeg.exe",
]


class FFmpegNotFound(RuntimeError):
    pass


def _find_in_path(names):
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def _search_windows(name: str):
    import glob

    for cand in _WIN_FALLBACKS:
        if os.path.basename(cand).startswith(name):
            if os.path.isfile(cand):
                return cand
    for pattern in _WIN_GLOBS:
        try:
            hits = sorted(glob.glob(pattern, recursive=True))
        except Exception:
            continue
        for hit in hits:
            if os.path.basename(hit).startswith(name):
                return hit
    # 遍历常见盘符的 ProgramFiles 目录
    for root in (r"C:\Program Files", r"C:\Program Files (x86)", r"D:\ProgramFiles"):
        if not os.path.isdir(root):
            continue
        try:
            for entry in os.listdir(root):
                if "ffmpeg" not in entry.lower():
                    continue
                for sub in ("bin", os.path.join("ffmpeg-8.1-full_build", "bin")):
                    cand = os.path.join(root, entry, sub, f"{name}.exe")
                    if os.path.isfile(cand):
                        return cand
        except OSError:
            continue
    return None


def locate():
    """返回 ``(ffmpeg_path, ffprobe_path)``，找不到则抛出异常。"""
    ffmpeg = _find_in_path(["ffmpeg", "ffmpeg.exe"])
    ffprobe = _find_in_path(["ffprobe", "ffprobe.exe"])

    if not ffmpeg and sys.platform == "win32":
        ffmpeg = _search_windows("ffmpeg")
    if not ffprobe:
        if ffmpeg:
            cand = os.path.join(os.path.dirname(ffmpeg), "ffprobe.exe" if sys.platform == "win32" else "ffprobe")
            if os.path.isfile(cand):
                ffprobe = cand
        if not ffprobe and sys.platform == "win32":
            ffprobe = _search_windows("ffprobe")

    if not ffmpeg:
        raise FFmpegNotFound(
            "未在系统环境变量 PATH 中找到 ffmpeg。\n\n"
            "请先安装 ffmpeg 并将其 bin 目录加入 PATH 环境变量，然后重新启动本程序。\n"
            "（下载地址：https://www.gyan.dev/ffmpeg/builds/）"
        )
    return ffmpeg, ffprobe or ffmpeg


def ffmpeg_version(ffmpeg_path: str) -> str:
    try:
        out = subprocess.run(
            [ffmpeg_path, "-version"], text=True, timeout=15, **popen_kwargs()
        )
        first = (out.stdout or "").splitlines()
        return first[0].strip() if first else "未知版本"
    except Exception:
        return "未知版本"


# --------------------------------------------------------------------------
# 媒体信息
# --------------------------------------------------------------------------
def _fraction(value) -> float:
    try:
        if isinstance(value, str) and "/" in value:
            num, den = value.split("/", 1)
            den = float(den)
            return float(num) / den if den else 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


class StreamInfo:
    """单个流的简化信息。"""

    __slots__ = (
        "index", "type", "codec", "profile", "width", "height", "fps",
        "sample_rate", "channels", "channel_layout", "bit_rate", "duration",
        "lang", "title", "pix_fmt", "raw",
    )

    def __init__(self, raw: dict):
        self.raw = raw
        self.index = _to_int(raw.get("index"), -1)
        self.type = raw.get("codec_type", "unknown")
        self.codec = raw.get("codec_name", "unknown")
        self.profile = raw.get("profile", "")
        self.width = _to_int(raw.get("width"))
        self.height = _to_int(raw.get("height"))
        self.fps = _fraction(raw.get("avg_frame_rate") or raw.get("r_frame_rate"))
        self.sample_rate = _to_int(raw.get("sample_rate"))
        self.channels = _to_int(raw.get("channels"))
        self.channel_layout = raw.get("channel_layout", "")
        self.bit_rate = _to_int(raw.get("bit_rate"))
        self.duration = float(raw.get("duration") or 0.0)
        self.pix_fmt = raw.get("pix_fmt", "")
        tags = raw.get("tags") or {}
        self.lang = tags.get("language", "")
        self.title = tags.get("title", "")

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}" if self.width and self.height else ""

    @property
    def type_cn(self) -> str:
        return {
            "video": "视频",
            "audio": "音频",
            "subtitle": "字幕",
            "data": "数据",
            "attachment": "附件",
        }.get(self.type, self.type)

    def summary(self) -> str:
        bits = [f"#{self.index}", self.type_cn, self.codec]
        if self.type == "video":
            if self.resolution:
                bits.append(self.resolution)
            if self.fps:
                bits.append(f"{self.fps:.3g} fps")
            if self.pix_fmt:
                bits.append(self.pix_fmt)
        elif self.type == "audio":
            if self.sample_rate:
                bits.append(f"{self.sample_rate} Hz")
            if self.channels:
                bits.append(f"{self.channels}ch")
        if self.bit_rate:
            from .util import human_bitrate

            bits.append(human_bitrate(self.bit_rate))
        if self.lang:
            bits.append(self.lang)
        if self.title:
            bits.append(f"「{self.title}」")
        return " · ".join(bits)


class MediaInfo:
    """一个媒体文件的整体信息。"""

    def __init__(self, path: str, raw: dict):
        self.path = path
        self.raw = raw or {}
        fmt = self.raw.get("format") or {}
        self.format_name = (fmt.get("format_name") or "").split(",")[0]
        self.format_long = fmt.get("format_long_name", "")
        self.duration = float(fmt.get("duration") or 0.0)
        self.size = _to_int(fmt.get("size"))
        self.bit_rate = _to_int(fmt.get("bit_rate"))
        self.nb_streams = _to_int(fmt.get("nb_streams"), len(self.raw.get("streams") or []))
        self.streams = [StreamInfo(s) for s in (self.raw.get("streams") or [])]
        self.tags = fmt.get("tags") or {}
        if not self.duration:
            for s in self.streams:
                if s.duration:
                    self.duration = max(self.duration, s.duration)

    # -- 便捷访问 ---------------------------------------------------------
    @property
    def video(self) -> StreamInfo | None:
        for s in self.streams:
            if s.type == "video" and not s.raw.get("disposition", {}).get("attached_pic"):
                return s
        return None

    @property
    def audio(self) -> StreamInfo | None:
        return next((s for s in self.streams if s.type == "audio"), None)

    @property
    def has_video(self) -> bool:
        return self.video is not None

    @property
    def has_audio(self) -> bool:
        return self.audio is not None

    @property
    def is_image(self) -> bool:
        return self.format_name in {"image2", "png_pipe", "jpeg_pipe", "webp_pipe", "bmp_pipe"} or (
            self.has_video and not self.has_audio and (self.duration or 0) < 0.05
        )

    def describe(self) -> str:
        """一行式摘要，用于状态栏。"""
        from .util import human_bitrate, human_duration, human_size

        parts = []
        v = self.video
        if v:
            parts.append(v.resolution)
            if v.fps:
                parts.append(f"{v.fps:.3g}fps")
            parts.append(v.codec)
        a = self.audio
        if a:
            parts.append(f"{a.codec} {a.channels}ch")
        parts.append(human_duration(self.duration))
        parts.append(human_size(self.size))
        parts.append(human_bitrate(self.bit_rate))
        return " · ".join(p for p in parts if p)


def probe(ffprobe_path: str, path: str, timeout: int = 30) -> MediaInfo:
    """调用 ffprobe 读取媒体信息（失败抛出 RuntimeError）。"""
    cmd = [
        ffprobe_path, "-v", "error", "-hide_banner",
        "-print_format", "json",
        "-show_format", "-show_streams",
        "-i", path,
    ]
    try:
        proc = subprocess.run(cmd, text=True, timeout=timeout, **popen_kwargs())
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"读取媒体信息超时：{os.path.basename(path)}") from None
    except OSError as exc:
        raise RuntimeError(f"无法执行 ffprobe：{exc}") from None

    if proc.returncode != 0:
        msg = (proc.stderr or "").strip().splitlines()
        raise RuntimeError(msg[-1] if msg else "ffprobe 返回错误")
    try:
        raw = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        raise RuntimeError("ffprobe 输出解析失败") from None
    return MediaInfo(path, raw)


# --------------------------------------------------------------------------
# 编解码器 / 滤镜能力探测
# --------------------------------------------------------------------------
_encoder_cache: set[str] | None = None
_filter_cache: set[str] | None = None


def available_encoders(ffmpeg_path: str) -> set[str]:
    """返回 ffmpeg 支持的编码器名称集合（结果缓存）。"""
    global _encoder_cache
    if _encoder_cache is not None:
        return _encoder_cache
    names: set[str] = set()
    try:
        out = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-encoders"],
            text=True, timeout=30, **popen_kwargs(),
        )
        for line in (out.stdout or "").splitlines():
            parts = line.split()
            if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] in "VAS":
                names.add(parts[1])
    except Exception:
        pass
    _encoder_cache = names
    return names


def available_filters(ffmpeg_path: str) -> set[str]:
    global _filter_cache
    if _filter_cache is not None:
        return _filter_cache
    names: set[str] = set()
    try:
        out = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-filters"],
            text=True, timeout=30, **popen_kwargs(),
        )
        for line in (out.stdout or "").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].startswith(("T", ".", "S", "V", "A")):
                names.add(parts[1])
    except Exception:
        pass
    _filter_cache = names
    return names


def pick_font() -> str:
    """挑选一个存在的中文字体文件路径。"""
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\Deng.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return ""
