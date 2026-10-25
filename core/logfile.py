# -*- coding: utf-8 -*-
"""把控制台（日志面板）的输出实时追加到程序目录的 ``log/`` 下。

排查问题时要的是「当时到底发生了什么」，所以：

* **逐行落盘并 flush**：不等界面那 120ms 的批量刷新，界面卡住或进程被
  掐掉时日志仍然完整；
* **一次运行一个文件**（``run-年月日-时分秒.log``），只追加不覆盖，
  历史 runs 都留着，按年龄自动回收；
* **签名参数先抹掉**：在线 m3u8 地址的 ``?sign=…&token=…`` 是会被人贴到
  群里求助的，不能跟着日志一起泄露。
"""
from __future__ import annotations

import os
import platform
import re
import sys
import time

from .util import APP_ROOT

LOG_DIR_NAME = "log"
LOG_KEEP_DAYS = 30.0
_URL_QUERY_RE = re.compile(r"(https?://[^\s\"'\\]+?)\?[^\s\"'\\]*")


def redact_secrets(text: str) -> str:
    """隐去 URL 的查询串（签名、token 一类凭据通常都在这里）。"""
    return _URL_QUERY_RE.sub(r"\1?<参数已隐藏>", str(text))


class RunLog:
    """日志文件写入器；任何 IO 失败都只影响落盘，绝不打断界面。"""

    def __init__(self, directory: str = "", keep_days: float = LOG_KEEP_DAYS):
        self.dir = directory or os.path.join(APP_ROOT, LOG_DIR_NAME)
        self.path = ""
        self._fh = None
        try:
            # 注意别用 util.ensure_dir()：它建的是「文件路径的父目录」
            os.makedirs(self.dir, exist_ok=True)
            self._purge(keep_days)
            base = os.path.join(self.dir, f"run-{time.strftime('%Y%m%d-%H%M%S')}")
            self.path = base + ".log"
            # 同一秒内重开（或自检里再建一个）就换个名字，别把两次运行混进同一份
            for n in range(1, 50):
                if not os.path.exists(self.path):
                    break
                self.path = f"{base}-{n}.log"
            self._fh = open(self.path, "a", encoding="utf-8", errors="replace",
                            buffering=1)
        except OSError:
            self._fh = None
            self.path = ""

    @property
    def enabled(self) -> bool:
        return self._fh is not None

    def write(self, line, kind: str = "info"):
        if self._fh is None:
            return
        try:
            stamp = time.strftime("%H:%M:%S")
            self._fh.write(f"{stamp} [{kind:<5s}] {redact_secrets(line).rstrip()}\n")
            self._fh.flush()
        except (OSError, ValueError):
            # 磁盘满、目录被删、编码意外……都不能把主流程带崩
            self._fh = None

    def header(self, fields) -> None:
        """开头写一段环境信息：报障时最常被问到的就是这些。"""
        self.write("=" * 60, "dim")
        self.write(f"启动时间 {time.strftime('%Y-%m-%d %H:%M:%S')} · "
                   f"Python {platform.python_version()} · {platform.system()} "
                   f"{platform.release()}", "dim")
        self.write("命令行 " + redact_secrets(" ".join(sys.argv)), "dim")
        for key, value in fields:
            if value:
                self.write(f"{key}：{redact_secrets(value)}", "dim")

    def close(self):
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None

    def _purge(self, keep_days: float) -> int:
        """按年龄回收旧日志（只认自己生成的 run-*.log，别碰用户放进来的东西）。"""
        if not keep_days or not os.path.isdir(self.dir):
            return 0
        cutoff = time.time() - keep_days * 86400.0
        removed = 0
        for name in os.listdir(self.dir):
            if not (name.startswith("run-") and name.endswith(".log")):
                continue
            path = os.path.join(self.dir, name)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed += 1
            except OSError:
                continue
        return removed
