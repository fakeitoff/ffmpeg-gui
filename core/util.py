# -*- coding: utf-8 -*-
"""通用工具：时间解析 / 格式化 / 路径处理 / ffmpeg 滤镜转义。"""
from __future__ import annotations

import os
import re
import subprocess
import sys

IS_WIN = sys.platform == "win32"
# 运行子进程时不弹出黑色控制台窗口（仅 Windows 有效）
CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0

# 程序根目录（core/ 的上一级）
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_PLAIN_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([hms]?)$", re.I)


def popen_kwargs(**extra):
    """构建 subprocess 通用参数，隐藏子进程控制台窗口。"""
    kw = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if IS_WIN:
        kw["creationflags"] = CREATE_NO_WINDOW
    kw.update(extra)
    return kw


# --------------------------------------------------------------------------
# 时间
# --------------------------------------------------------------------------
def parse_time(text) -> float | None:
    """把用户输入的时间解析为秒。

    支持：``90``、``90s``、``1.5m``、``1h``、``1:30``、``00:01:30.250``。
    空字符串返回 ``None``。
    """
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None

    if ":" in s:
        parts = s.split(":")
        if len(parts) > 3:
            raise ValueError(f"时间格式无法识别：{text}")
        total = 0.0
        for p in parts:
            p = p.strip()
            if p == "":
                continue
            try:
                total = total * 60 + float(p)
            except ValueError:
                raise ValueError(f"时间格式无法识别：{text}") from None
        return total

    m = _PLAIN_RE.match(s)
    if not m:
        raise ValueError(f"时间格式无法识别：{text}")
    value = float(m.group(1))
    unit = (m.group(2) or "s").lower()
    return value * {"s": 1.0, "m": 60.0, "h": 3600.0}[unit]


def format_time(seconds, precision: int = 3) -> str:
    """秒 -> ``HH:MM:SS.mmm``（ffmpeg 通用时间写法）。"""
    if seconds is None:
        return "0"
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    if precision <= 0:
        return f"{h:02d}:{m:02d}:{int(s):02d}"
    width = 3 + precision
    return f"{h:02d}:{m:02d}:{s:0{width}.{precision}f}"


def human_duration(seconds) -> str:
    """秒 -> 人类可读时长。"""
    if not seconds:
        return "--:--"
    seconds = float(seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    if h:
        return f"{h}:{m:02d}:{int(s):02d}"
    return f"{m}:{int(s):02d}"


def human_size(num) -> str:
    """字节 -> 人类可读体积。"""
    if num is None:
        return "-"
    num = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(num)} B"
            return f"{num:.2f} {unit}"
        num /= 1024.0
    return f"{num:.2f} TB"


def human_bitrate(bps) -> str:
    if not bps:
        return "-"
    bps = float(bps)
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.2f} Mbps"
    if bps >= 1000:
        return f"{bps / 1000:.0f} kbps"
    return f"{int(bps)} bps"


# --------------------------------------------------------------------------
# 路径
# --------------------------------------------------------------------------
def stem_of(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def ext_of(path: str) -> str:
    return os.path.splitext(path)[1].lstrip(".").lower()


def replace_ext(path: str, new_ext: str) -> str:
    new_ext = new_ext.lstrip(".")
    root, _ = os.path.splitext(path)
    return f"{root}.{new_ext}"


def build_output_name(src: str, suffix: str, ext: str) -> str:
    """在源文件同目录下生成 ``<名字><后缀>.<扩展名>``。"""
    base = f"{stem_of(src)}{suffix}"
    return os.path.join(os.path.dirname(os.path.abspath(src)), f"{base}.{ext.lstrip('.')}")


def build_output_in_dir(src: str, out_dir: str, suffix: str, ext: str) -> str:
    base = f"{stem_of(src)}{suffix}"
    return os.path.join(out_dir, f"{base}.{ext.lstrip('.')}")


def unique_path(path: str) -> str:
    """若文件已存在则追加 ``_1``、``_2`` ……"""
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    i = 1
    while True:
        cand = f"{root}_{i}{ext}"
        if not os.path.exists(cand):
            return cand
        i += 1


def natural_key(text: str):
    """自然排序键：``a2`` 排在 ``a10`` 前面。"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(text))]


def same_file(a: str, b: str) -> bool:
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except Exception:
        return False


def open_in_explorer(path: str):
    """在文件管理器中定位文件（Windows 为资源管理器）。"""
    path = os.path.abspath(path)
    if IS_WIN:
        if os.path.isdir(path):
            os.startfile(path)  # noqa: S606
        else:
            subprocess.Popen(["explorer", "/select,", path])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R" if os.path.isfile(path) else "", path])
    else:
        target = path if os.path.isdir(path) else os.path.dirname(path)
        subprocess.Popen(["xdg-open", target])


# --------------------------------------------------------------------------
# 滤镜参数转义
# --------------------------------------------------------------------------
def escape_filter_value(value: str) -> str:
    """转义 ffmpeg 滤镜图中的取值。

    需要转义的字符：``\\ ' : , ; [ ] =``。运行时不经过 shell，
    因此只需处理 ffmpeg 自身的滤镜解析规则。
    """
    out = []
    for ch in str(value):
        if ch in "\\'\":,;[]=":
            out.append("\\")
        out.append(ch)
    return "".join(out)


def escape_filter_path(path: str) -> str:
    """把本地路径转换为可安全嵌入滤镜图的写法。

    ``C:\\Users\\a b\\x.srt`` -> ``C\\:/Users/a b/x.srt``
    """
    p = os.path.abspath(path).replace("\\", "/")
    return escape_filter_value(p)


def quote_arg(arg: str) -> str:
    """把单个参数包装成可读 / 可粘贴到命令行的形式。"""
    if arg == "":
        return '""'
    if re.search(r'[\s"&|<>^()]', arg):
        return '"' + arg.replace('"', r"\"") + '"'
    return arg


def cmd_to_string(args) -> str:
    return " ".join(quote_arg(a) for a in args)


def split_command(text: str) -> list[str]:
    """把命令行文本拆成参数列表（Windows 友好：反斜杠按字面处理）。"""
    import shlex

    lex = shlex.shlex(str(text), posix=False)
    lex.whitespace_split = True
    lex.commenters = ""
    tokens = list(lex)
    out = []
    for tok in tokens:
        if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'":
            tok = tok[1:-1]
        out.append(tok)
    return out


# 执行器会自动添加的全局参数，用户若重复填写则忽略
_GLOBAL_FLAGS = {"-hide_banner", "-nostats", "-y", "-n"}
_GLOBAL_PAIRS = {"-loglevel", "-progress", "-v"}


def strip_global_args(tokens: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in _GLOBAL_FLAGS:
            i += 1
            continue
        if tok in _GLOBAL_PAIRS:
            i += 2
            continue
        out.append(tok)
        i += 1
    return out


def ensure_dir(path: str):
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


# 本程序在临时目录中使用的文件名前缀（只清理自己的东西）
TEMP_PREFIXES = ("ffgui_concat_", "ffgui_drawtext_", "ffgui_test_")
# 早期版本用 mkstemp(prefix="ffgui_") 生成的随机名文件，当前版本已不再产生
_TEMP_LEGACY_RE = re.compile(r"^ffgui_[0-9a-z_]{8}\.txt$")


_local_temp_cache: str | None = None


def local_temp_dir() -> str:
    """返回本程序专用的临时目录：``<程序根目录>/temp``。

    放在程序自己的目录下，位置直观、方便用户随时手动清空；
    若程序目录不可写（例如装在 Program Files），自动退回系统临时目录。
    结果按进程缓存，避免每次生成命令都去做一次写权限探测。
    """
    global _local_temp_cache
    if _local_temp_cache:
        return _local_temp_cache

    preferred = os.path.join(APP_ROOT, "temp")
    try:
        os.makedirs(preferred, exist_ok=True)
        import tempfile as _tf

        fd, probe = _tf.mkstemp(dir=preferred, prefix=".probe_")
        os.close(fd)
        os.remove(probe)
        _local_temp_cache = preferred
    except OSError:
        import tempfile

        fallback = os.path.join(tempfile.gettempdir(), "ffmpeg-gui")
        os.makedirs(fallback, exist_ok=True)
        _local_temp_cache = fallback
    return _local_temp_cache


def purge_dir(directory: str, max_age_hours: float = 0.0,
              skip: str = "", pattern: str = "*") -> int:
    """删除目录中超过指定年龄的文件（0 表示全部），返回删除数量。"""
    import glob
    import shutil
    import time

    if not os.path.isdir(directory):
        return 0
    cutoff = time.time() - max_age_hours * 3600.0
    skip = os.path.abspath(skip) if skip else ""
    removed = 0
    for path in glob.glob(os.path.join(directory, pattern)):
        try:
            if skip and os.path.abspath(path) == skip:
                continue
            if os.path.getmtime(path) > cutoff:
                continue
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
            removed += 1
        except OSError:
            continue
    return removed


def purge_stale_temp(max_age_hours: float = 24.0) -> int:
    """清理**旧版本**遗留在系统临时目录里的 ``ffgui_*`` 文件。

    当前版本已改为把临时文件放在程序目录的 ``temp/`` 下
    （见 :func:`local_temp_dir`），此函数仅用于回收历史残留。
    """
    import glob
    import tempfile

    tempdir = tempfile.gettempdir()
    cutoff_paths: list[str] = []
    for prefix in TEMP_PREFIXES:
        cutoff_paths += glob.glob(os.path.join(tempdir, f"{prefix}*"))
    legacy_dir = os.path.join(tempdir, "ffgui_*.txt")
    cutoff_paths += [p for p in glob.glob(legacy_dir)
                     if _TEMP_LEGACY_RE.match(os.path.basename(p))]

    import time

    cutoff = time.time() - max_age_hours * 3600.0
    removed = 0
    for path in set(cutoff_paths):
        if _TEMP_LEGACY_RE.match(os.path.basename(path)):
            pass                                  # 旧随机名文件：当前版本不会再生成
        elif os.path.getmtime(path) > cutoff:
            continue
        try:
            if os.path.isdir(path):
                import shutil

                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
            removed += 1
        except OSError:
            continue
    return removed
