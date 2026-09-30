# -*- coding: utf-8 -*-
"""ffmpeg 进程执行与进度解析。"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass, field

from .util import cmd_to_string, ensure_dir, popen_kwargs

# 全局通用参数（必须放在所有输入文件之前）
GLOBAL_ARGS = ["-hide_banner", "-nostats", "-progress", "pipe:1"]

LOG_LEVELS = ["quiet", "panic", "fatal", "error", "warning", "info", "verbose", "debug"]


@dataclass
class Job:
    """一次转码任务。"""

    src: str
    dst: str
    args: list[str]          # 不含 ffmpeg 可执行文件与全局参数，含 -i 与输出文件
    duration: float = 0.0    # 源文件时长（秒），用于计算进度
    label: str = ""
    aux_files: list[str] = field(default_factory=list)   # 任务结束后需要清理的辅助文件

    def command(self, ffmpeg_path: str, loglevel: str = "info", overwrite: bool = True) -> list[str]:
        flag = "-y" if overwrite else "-n"
        return [ffmpeg_path] + GLOBAL_ARGS + [flag, "-loglevel", loglevel] + self.args

    def preview(self, ffmpeg_path: str = "ffmpeg", loglevel: str = "info") -> str:
        return cmd_to_string(self.command(ffmpeg_path, loglevel))


@dataclass
class Progress:
    job_index: int = 0
    job_total: int = 1
    percent: float = 0.0
    overall: float = 0.0
    out_time: float = 0.0
    speed: str = ""
    fps: str = ""
    size: str = ""
    frame: str = ""
    state: str = "idle"      # idle / running / done / error / cancelled
    elapsed: float = 0.0     # 本任务已运行秒数
    has_duration: bool = True   # 是否知道预期总时长（否则无法算百分比）


class JobRunner(threading.Thread):
    """在后台线程中依次执行多个 Job。

    所有回调都在后台线程中触发，UI 层需自行切回主线程。
    """

    def __init__(self, jobs: list[Job], ffmpeg_path: str, loglevel: str = "info",
                 on_log=None, on_progress=None, on_job_start=None, on_job_done=None,
                 on_finished=None, overwrite: bool = True):
        super().__init__(daemon=True)
        self.jobs = jobs
        self.ffmpeg_path = ffmpeg_path
        self.loglevel = loglevel
        self.on_log = on_log or (lambda line, kind="info": None)
        self.on_progress = on_progress or (lambda p: None)
        self.on_job_start = on_job_start or (lambda i, job: None)
        self.on_job_done = on_job_done or (lambda i, job, ok, msg: None)
        self.on_finished = on_finished or (lambda ok, msg: None)
        self.overwrite = overwrite

        self._proc: subprocess.Popen | None = None
        # 注意：不要把这个 Event 命名为 self._stop —— 那会覆盖
        # threading.Thread 的内部方法 _stop()，导致线程结束后
        # is_alive() 抛 TypeError（历史上踩过这个坑）。
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self.results: list[tuple[str, bool, str]] = []

    # -- 控制 -------------------------------------------------------------
    def cancel(self):
        self._stop_event.set()
        with self._lock:
            proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
            for _ in range(20):
                if proc.poll() is not None:
                    break
                time.sleep(0.05)
            if proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass

    @property
    def cancelled(self) -> bool:
        return self._stop_event.is_set()

    # -- 主流程 -----------------------------------------------------------
    def run(self):
        total = len(self.jobs)
        ok_all = True
        message = ""
        for i, job in enumerate(self.jobs):
            if self._stop_event.is_set():
                ok_all = False
                message = "已取消"
                break
            self.on_job_start(i, job)
            ok, msg = self._run_one(i, total, job)
            self.results.append((job.dst, ok, msg))
            self.on_job_done(i, job, ok, msg)
            if not ok:
                ok_all = False
                if self._stop_event.is_set():
                    message = "已取消"
                    break
                message = msg
                break
        if ok_all:
            message = f"全部完成（{total} 个任务）" if total > 1 else "完成"
        self.on_finished(ok_all, message)

    def _run_one(self, index: int, total: int, job: Job):
        ensure_dir(job.dst)
        cmd = job.command(self.ffmpeg_path, self.loglevel, self.overwrite)
        self.on_log(f"$ {cmd_to_string(cmd)}", "cmd")

        try:
            proc = subprocess.Popen(
                cmd, text=True, encoding="utf-8", errors="replace",
                bufsize=1, **popen_kwargs(),
            )
        except OSError as exc:
            return False, f"无法启动 ffmpeg：{exc}"

        with self._lock:
            self._proc = proc

        errors: list[str] = []
        progress_holder = {
            "out_time": 0.0, "speed": "", "fps": "", "frame": "", "size": "",
            "started": time.time(),
        }

        def pump_stderr():
            try:
                for raw in proc.stderr:
                    if not raw:
                        break
                    line = raw.rstrip("\r\n")
                    if not line.strip():
                        continue
                    low = line.lower()
                    if "error" in low or "invalid" in low or "failed" in low or "no such" in low:
                        errors.append(line)
                        self.on_log(line, "error")
                    elif "warning" in low or "deprecated" in low:
                        self.on_log(line, "warn")
                    else:
                        self.on_log(line, "info")
            except Exception:
                pass

        def pump_progress():
            try:
                for raw in proc.stdout:
                    if not raw:
                        break
                    line = raw.strip()
                    if not line or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    val = val.strip()
                    if key in ("out_time_us", "out_time_ms"):
                        try:
                            us = int(val)
                        except ValueError:
                            continue
                        # 新版 ffmpeg 的 out_time_ms 实际也是微秒
                        sec = us / 1_000_000.0
                        if sec > progress_holder["out_time"]:
                            progress_holder["out_time"] = sec
                    elif key == "speed":
                        progress_holder["speed"] = val
                    elif key == "fps":
                        progress_holder["fps"] = val
                    elif key == "frame":
                        progress_holder["frame"] = val
                    elif key == "total_size":
                        try:
                            from .util import human_size
                            progress_holder["size"] = human_size(int(val))
                        except ValueError:
                            pass

                    if key == "progress":
                        self._emit(index, total, job, progress_holder, "running")
                        if val == "end":
                            self._emit(index, total, job, progress_holder, "done")
            except Exception:
                pass

        t_err = threading.Thread(target=pump_stderr, daemon=True)
        t_prg = threading.Thread(target=pump_progress, daemon=True)
        t_err.start()
        t_prg.start()

        rc = proc.wait()
        t_prg.join(timeout=3)
        t_err.join(timeout=3)

        with self._lock:
            self._proc = None

        if self._stop_event.is_set():
            try:
                if os.path.exists(job.dst):
                    os.remove(job.dst)
            except OSError:
                pass
            self._drop_aux(job)
            return False, "已取消"

        if rc != 0:
            detail = errors[-1] if errors else f"ffmpeg 退出码 {rc}"
            self._drop_aux(job)
            return False, detail

        self._drop_aux(job)
        if not os.path.exists(job.dst) or os.path.getsize(job.dst) == 0:
            return False, "输出文件未生成或为空"
        return True, "完成"

    @staticmethod
    def _drop_aux(job: Job):
        """清理本任务用到的辅助文件（如拼接清单）。"""
        for path in job.aux_files:
            try:
                os.remove(path)
            except OSError:
                pass

    def _emit(self, index, total, job, holder, state):
        duration = job.duration or 0.0
        out_time = holder["out_time"]
        pct = min(100.0, (out_time / duration) * 100.0) if duration > 0 else 0.0
        overall = ((index + pct / 100.0) / max(1, total)) * 100.0
        p = Progress(
            job_index=index,
            job_total=total,
            percent=pct,
            overall=overall,
            out_time=out_time,
            speed=holder["speed"],
            fps=holder["fps"],
            size=holder["size"],
            frame=holder["frame"],
            state=state,
            elapsed=max(0.0, time.time() - holder.get("started", time.time())),
            has_duration=duration > 0,
        )
        self.on_progress(p)
