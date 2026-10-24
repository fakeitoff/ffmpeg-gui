# -*- coding: utf-8 -*-
"""命令片段构建：编码器、滤镜链等复用逻辑。"""
from __future__ import annotations

# --------------------------------------------------------------------------
# 编码器
# --------------------------------------------------------------------------
VIDEO_ENCODERS = [
    ("copy", "直接复制（不重新编码，最快）"),
    ("libx264", "H.264 / AVC（兼容性最好）"),
    ("libx265", "H.265 / HEVC（体积更小）"),
    ("libvpx-vp9", "VP9（WebM 常用）"),
    ("libsvtav1", "AV1（最高压缩率，较慢）"),
    ("libaom-av1", "AV1 (libaom，很慢)"),
    ("mpeg4", "MPEG-4 Part 2"),
    ("prores_ks", "Apple ProRes"),
    ("h264_nvenc", "H.264 · NVIDIA 硬件编码"),
    ("hevc_nvenc", "H.265 · NVIDIA 硬件编码"),
    ("av1_nvenc", "AV1 · NVIDIA 硬件编码"),
    ("h264_qsv", "H.264 · Intel 快速同步"),
    ("hevc_qsv", "H.265 · Intel 快速同步"),
    ("h264_amf", "H.264 · AMD 硬件编码"),
    ("hevc_amf", "H.265 · AMD 硬件编码"),
    ("h264_videotoolbox", "H.264 · Apple VideoToolbox"),
    ("hevc_videotoolbox", "H.265 · Apple VideoToolbox"),
    ("gif", "GIF 动图"),
]

AUDIO_ENCODERS = [
    ("copy", "直接复制（不重新编码）"),
    ("aac", "AAC（mp4/mkv 通用）"),
    ("libmp3lame", "MP3"),
    ("libopus", "Opus（webm/ogg）"),
    ("libvorbis", "Vorbis（ogg）"),
    ("ac3", "AC-3（DVD 兼容）"),
    ("flac", "FLAC 无损"),
    ("pcm_s16le", "PCM 16bit（wav）"),
    ("pcm_s24le", "PCM 24bit（wav）"),
    ("libfdk_aac", "AAC (libfdk)"),
]

PRESETS = [
    "ultrafast", "superfast", "veryfast", "faster", "fast",
    "medium", "slow", "slower", "veryslow", "placebo",
]

# 每个容器推荐的（视频编码器, 音频编码器, GPU/CPU）
CONTAINER_VIDEO = {
    "mp4": ["libx264", "libx265", "h264_nvenc", "hevc_nvenc", "mpeg4", "libsvtav1"],
    "m4v": ["libx264", "mpeg4"],
    "mkv": ["libx264", "libx265", "libvpx-vp9", "libsvtav1", "prores_ks"],
    "mov": ["libx264", "libx265", "prores_ks", "libsvtav1"],
    "webm": ["libvpx-vp9", "libsvtav1", "libaom-av1"],
    "avi": ["mpeg4", "libx264"],
    "flv": ["libx264"],
    "ts": ["libx264", "libx265"],
    "wmv": ["wmv2"],
    "ogv": ["libtheora"],
    "gif": ["gif"],
}

CONTAINER_AUDIO = {
    "mp4": ["aac", "ac3", "libmp3lame"],
    "m4v": ["aac"],
    "mkv": ["aac", "libopus", "flac", "ac3", "libmp3lame"],
    "mov": ["aac", "pcm_s16le"],
    "webm": ["libopus", "libvorbis"],
    "avi": ["libmp3lame", "pcm_s16le"],
    "flv": ["aac", "libmp3lame"],
    "ts": ["aac"],
    "wmv": ["wmav2"],
    "ogv": ["libvorbis"],
    "gif": [],
}

AUDIO_ONLY_FORMATS = {
    "mp3": ("libmp3lame", "mp3"),
    "m4a": ("aac", "m4a"),
    "aac": ("aac", "aac"),
    "wav": ("pcm_s16le", "wav"),
    "flac": ("flac", "flac"),
    "ogg": ("libvorbis", "ogg"),
    "opus": ("libopus", "opus"),
    "wma": ("wmav2", "wma"),
    "ac3": ("ac3", "ac3"),
    "mka": ("flac", "mka"),
}


def guess_container(filename: str) -> str:
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    return ext or "mp4"


def container_supports(container: str, encoder: str) -> bool:
    """粗略判断容器是否接纳该编码器（用于灰显提示）。"""
    v = CONTAINER_VIDEO.get(container)
    a = CONTAINER_AUDIO.get(container)
    if v is None and a is None:
        return True
    return encoder in (v or []) or encoder in (a or [])


# --------------------------------------------------------------------------
# 编码参数
# --------------------------------------------------------------------------
def video_encode_args(encoder: str, **kw) -> list[str]:
    """生成视频编码参数。kw: crf / preset / bitrate / pix_fmt / gop / tune"""
    if encoder == "copy" or not encoder:
        return ["-c:v", "copy"]

    args = ["-c:v", encoder]
    is_hw = any(encoder.endswith(s) for s in ("_nvenc", "_qsv", "_amf", "_videotoolbox", "_vaapi"))

    crf = kw.get("crf")
    bitrate = kw.get("bitrate")
    preset = kw.get("preset")

    if encoder in ("gif",):
        return args

    if encoder in ("libx264", "libx265", "libvpx-vp9", "libsvtav1", "libaom-av1", "libxvid"):
        if bitrate:
            args += ["-b:v", str(bitrate)]
        elif crf is not None:
            args += ["-crf", str(crf)]
            if encoder in ("libvpx-vp9", "libaom-av1"):
                # VP9 / libaom 只有在目标码率为 0 时才走真正的恒定质量（CRF）模式，
                # 否则 -crf 只是给码率控制加了个质量上限，画质档位等于没生效。
                args += ["-b:v", "0"]
        if preset:
            if encoder in ("libx264", "libx265"):
                args += ["-preset", preset]
            elif encoder == "libsvtav1":
                args += ["-preset", str(min(13, max(0, PRESETS.index(preset) + 4)))]
        if encoder in ("libx264", "libx265") and kw.get("profile"):
            args += ["-profile:v", kw["profile"]]
    elif is_hw:
        if "qsv" in encoder:
            if bitrate:
                args += ["-b:v", str(bitrate)]
            elif crf is not None:
                # QSV 使用全局质量等级 1-51（数值越小越好）
                args += ["-global_quality", str(int(crf)), "-look_ahead", "1"]
        elif "videotoolbox" in encoder:
            if bitrate:
                args += ["-b:v", str(bitrate)]
            elif crf is not None:
                args += ["-q:v", str(max(1, min(100, 100 - int(crf * 2))))]
        else:  # nvenc / amf
            if bitrate:
                args += ["-b:v", str(bitrate)]
            elif crf is not None:
                # nvenc 用 -cq，amf 用 -qp_i/-qp_p
                if encoder.endswith("_nvenc"):
                    args += ["-rc", "vbr", "-cq", str(int(crf))]
                else:
                    args += ["-rc", "cqp", "-qp_i", str(int(crf)), "-qp_p", str(int(crf))]
    elif encoder == "prores_ks":
        args += ["-profile:v", str(kw.get("prores_profile", 3))]
    else:
        if bitrate:
            args += ["-b:v", str(bitrate)]
        elif crf is not None:
            args += ["-crf", str(crf)]

    if kw.get("pix_fmt"):
        args += ["-pix_fmt", kw["pix_fmt"]]
    if kw.get("gop"):
        args += ["-g", str(kw["gop"])]
    return args


def audio_encode_args(encoder: str, **kw) -> list[str]:
    """生成音频编码参数。kw: bitrate / sample_rate / channels"""
    if encoder == "copy" or not encoder:
        return ["-c:a", "copy"]

    args = ["-c:a", encoder]
    br = kw.get("bitrate")
    if br and encoder not in ("flac", "pcm_s16le", "pcm_s24le", "copy"):
        args += ["-b:a", str(br)]
    sr = kw.get("sample_rate")
    if sr:
        args += ["-ar", str(sr)]
    ch = kw.get("channels")
    if ch:
        args += ["-ac", str(ch)]
    return args


def quality_args(crf: int) -> list[str]:
    return ["-crf", str(crf)]


# --------------------------------------------------------------------------
# 字幕流
# --------------------------------------------------------------------------
# 文本类字幕（可以互相转码）；其余是图形字幕（PGS / VobSub 等），无法转成文本字幕。
TEXT_SUB_CODECS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "vtt",
                   "text", "tt", "eia_608", "dvb_teletext", "libzvbi_teletext"}

# 各容器接受的字幕编码差别很大，原样 copy 常见后果是写头时整体失败：
#   MP4 / MOV   只认 mov_text（TS/文本字幕都会被拒）
#   MKV         认 ass / srt / webvtt / PGS，但**不认 mov_text**（网上下载的 MP4 内嵌字幕就是它）
#   WebM        只认 webvtt


def subtitle_codec_args(codecs, container: str) -> list[str]:
    """按输出容器给每条字幕流指定编码器。

    ``codecs`` 是**映射顺序**下各字幕流的编码名（来自 ffprobe）。
    逐条用 ``-c:s:<序号>`` 指定，这样图形字幕仍能直接 copy ——
    统一写 ``-c:s ass`` 会让 PGS 之类无法转换的流整批失败。
    MKV 里只有 mov_text 需要转成 ass，其余保持原编码（省略参数即沿用 -c copy）。
    """
    args: list[str] = []
    for i, raw in enumerate(codecs or []):
        codec = str(raw or "").lower()
        if container in ("mp4", "mov", "m4v"):
            args += [f"-c:s:{i}", "mov_text"]
        elif container in ("mkv", "mka") and codec == "mov_text":
            args += [f"-c:s:{i}", "ass"]
        elif container == "webm" and codec in TEXT_SUB_CODECS:
            args += [f"-c:s:{i}", "webvtt"]
    return args


# --------------------------------------------------------------------------
# 滤镜
# --------------------------------------------------------------------------
def scale_filter(width=None, height=None, mode="fit", pad_color="black") -> str:
    """生成 scale/pad 滤镜。

    mode:
      * ``fit``   等比缩放到框内，保持宽高比（可能改变尺寸）
      * ``pad``   等比缩放后补黑边到目标尺寸
      * ``crop``  等比放大后裁剪到目标尺寸（填满不留边）
      * ``stretch`` 强制拉伸
    """
    if not width and not height:
        return ""
    w = str(width) if width else "-2"
    h = str(height) if height else "-2"

    if mode == "stretch" and width and height:
        return f"scale={width}:{height}"
    if mode == "fit":
        # scale=W:H 会把画面强行拉成 W×H（比例失真）；只有加了
        # force_original_aspect_ratio=decrease 才是「等比缩放到框内」。
        if width and height:
            return f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos"
        return f"scale={w}:{h}:flags=lanczos"
    if width and height:
        if mode == "pad":
            return (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={pad_color}"
            )
        if mode == "crop":
            return (
                f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={width}:{height}"
            )
    return f"scale={w}:{h}:flags=lanczos"


def atempo_chain(speed: float) -> str:
    """atempo 单次只支持 0.5~2.0，超出时串联。"""
    if speed <= 0:
        speed = 1.0
    parts = []
    remaining = speed
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append(f"atempo={remaining:.6f}".rstrip("0").rstrip("."))
    return ",".join(parts)


def drawtext_filter(textfile_escaped: str, font_escaped: str, size=32, color="white",
                    border=2, border_color="black", x="20", y="20", alpha=1.0,
                    box=False, box_color="black@0.5", box_border=8,
                    font_size_expr=None, extra: str = "") -> str:
    """构建单行 drawtext 滤镜串。

    文本走 ``textfile`` 参数（配合 ``expansion=none``）：中文、引号、冒号、
    方括号、百分号等全部原样输出，**完全不存在转义问题**。
    注意文本文件内容不要带换行——ffmpeg 会把换行符本身画成一个方块。
    """
    size_val = font_size_expr if font_size_expr else str(int(size))
    opts = [
        f"fontfile='{font_escaped}'",
        f"textfile='{textfile_escaped}'",
        "expansion=none",
        f"fontsize={size_val}",
        f"fontcolor={color}",
        f"x={x}",
        f"y={y}",
    ]
    if alpha < 1.0:
        opts.append(f"alpha={alpha:.3f}")
    if border and int(border) > 0:
        opts += [f"borderw={int(border)}", f"bordercolor={border_color}"]
    if box:
        opts += ["box=1", f"boxcolor={box_color}", f"boxborderw={int(box_border)}"]
    if extra:
        opts.append(extra)
    return "drawtext=" + ":".join(opts)


def drawtext_lines(textfiles_escaped: list[str], font_escaped: str, size=32,
                   color="white", border=2, border_color="black", x="20", y="20",
                   alpha=1.0, box=False, box_color="black@0.5", box_border=8,
                   line_spacing: float = 1.25) -> list[str]:
    """多行水印：每个文本文件对应一行，返回一组 drawtext 滤镜串。

    整块文字锚定在 ``y`` 位置——上对齐位置向下延伸，下对齐 / 居中位置向上回退，
    保证文字不会跑出画面。
    """
    files = list(textfiles_escaped) or [""]
    if len(files) == 1:
        return [drawtext_filter(files[0], font_escaped, size=size, color=color,
                                border=border, border_color=border_color, x=x, y=y,
                                alpha=alpha, box=box, box_color=box_color,
                                box_border=box_border)]

    lh = max(1, int(round(int(str(size)) * line_spacing)))
    n = len(files)
    ystr = str(y)
    if "H-h" in ystr or "H-" in ystr:
        base = f"{ystr}-{(n - 1) * lh}"
    elif ystr.strip().startswith("("):
        base = f"{ystr}-{(n - 1) * lh // 2}"
    else:
        base = ystr
    out = []
    for i, path in enumerate(files):
        yi = base if i == 0 else f"{base}+{i * lh}"
        out.append(drawtext_filter(path, font_escaped, size=size, color=color,
                                   border=border, border_color=border_color, x=x, y=yi,
                                   alpha=alpha, box=box, box_color=box_color,
                                   box_border=box_border))
    return out


def overlay_position(pos: str, margin: int = 20) -> str:
    """把位置关键字转换为 overlay 坐标表达式。"""
    m = int(margin)
    table = {
        "左上": f"{m}:{m}",
        "右上": f"W-w-{m}:{m}",
        "左下": f"{m}:H-h-{m}",
        "右下": f"W-w-{m}:H-h-{m}",
        "正中": "(W-w)/2:(H-h)/2",
        "上中": "(W-w)/2:{m}",
        "下中": "(W-w)/2:H-h-{m}",
        "左中": f"{m}:(H-h)/2",
        "右中": f"W-w-{m}:(H-h)/2",
    }
    return table.get(pos, table["右下"])
