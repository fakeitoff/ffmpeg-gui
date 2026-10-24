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
    duration: float = 0.0    # 源文件时长（秒），用于按时间估算进度
    total_frames: int = 0    # 视频总帧数，用于按实际处理帧数算进度（优先）
    label: str = ""
    aux_files: list[str] = field(default_factory=list)   # 任务结束后需要清理的辅助文件

    def command(self, ffmpeg_path: str, loglevel: str = "info", overwrite: bool = True) -> list[str]:
        flag = "-y" if overwrite else "-n"
        return [ffmpeg_path] + GLOBAL_ARGS + [flag, "-loglevel", loglevel] + self.args

    def preview(self, ffmpeg_path: str = "ffmpeg", loglevel: str = "info",
                overwrite: bool = True) -> str:
        return cmd_to_string(self.command(ffmpeg_path, loglevel, overwrite))


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
    frame_num: int = 0        # 已处理帧数（用于按帧算进度与展示）
    total_frames: int = 0     # 总帧数
    state: str = "idle"      # idle / running / done / error / cancelled
    elapsed: float = 0.0     # 本任务已运行秒数
    has_duration: bool = True   # 是否具备计算百分比的基础（帧数或时长）


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
        cancelled = False
        for i, job in enumerate(self.jobs):
            if self._stop_event.is_set():
                cancelled = True
                break
            self.on_job_start(i, job)
            ok, msg = self._run_one(i, total, job)
            self.results.append((job.dst, ok, msg))
            self.on_job_done(i, job, ok, msg)
            if not ok and self._stop_event.is_set():
                cancelled = True
                break
        # 辅助文件（拼接清单 / 水印文本）在所有任务跑完后统一清理。
        # 批量处理时多个任务引用的是同一批辅助文件，若每个任务结束就删，
        # 后面的任务会因找不到文件而失败。
        for job in self.jobs:
            self._drop_aux(job)

        done = sum(1 for _dst, ok, _msg in self.results if ok)
        failed = len(self.results) - done
        if cancelled:
            ok_all = False
            left = total - len(self.results)
            message = f"已取消：成功 {done} 个"
            if left:
                message += f"，未处理 {left} 个"
            if failed:
                message += f"，失败 {failed} 个"
        elif failed:
            # 批量任务里一个文件失败不该中断整批：继续跑完剩下的，最后汇总。
            ok_all = False
            bad = [os.path.basename(dst) for dst, ok, _m in self.results if not ok]
            names = "、".join(bad[:3]) + ("…" if len(bad) > 3 else "")
            message = f"成功 {done} 个，失败 {failed} 个：{names}"
        else:
            ok_all = True
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
            "out_time": 0.0, "speed": "", "fps": "", "frame": "", "frame_num": 0,
            "size": "", "started": time.time(), "pct": 0.0,
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
                        try:
                            progress_holder["frame_num"] = int(val)
                        except ValueError:
                            pass
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
            return False, "已取消"

        if rc != 0:
            self._drop_empty_output(job)
            detail = errors[-1] if errors else f"ffmpeg 退出码 {rc}"
            return False, detail

        if not self._output_ok(job, progress_holder.get("started", 0.0)):
            self._drop_empty_output(job)
            return False, "输出文件未生成或为空"
        return True, "完成"

    @staticmethod
    def _drop_empty_output(job: Job):
        """失败任务留下的 0 字节文件要清掉，否则用户会以为已经输出了。"""
        try:
            if os.path.isfile(job.dst) and os.path.getsize(job.dst) == 0:
                os.remove(job.dst)
        except OSError:
            pass

    @staticmethod
    def _output_ok(job: Job, since: float = 0.0) -> bool:
        """判断任务是否真的产出了文件。

        批量截图等模式的输出路径是含 ``%04d`` 的模板，磁盘上不存在同名文件，
        直接 ``os.path.exists`` 恒为 False，会被误判成「输出文件未生成或为空」
        并中断后续任务。这里先把占位符换成通配符再匹配实际产物
        （``_0001.jpg``、``_0002.jpg`` ……）。

        ``since`` 为本任务启动时刻：只统计该时刻之后生成的文件，
        避免把上一次运行残留的同名图片当成本次的成功产出。
        """
        dst = job.dst
        if os.path.exists(dst):
            return os.path.getsize(dst) > 0
        if "%" not in dst:
            return False
        import glob
        import re

        pattern = re.sub(r"%0?\d*[di]", "*", dst)
        try:
            matches = [p for p in glob.glob(pattern) if os.path.isfile(p)]
        except Exception:
            return False
        if since:
            matches = [p for p in matches if os.path.getmtime(p) >= since - 1.0]
        return any(os.path.getsize(p) > 0 for p in matches)

    @staticmethod
    def _drop_aux(job: Job):
        """清理本任务用到的辅助文件（如拼接清单）。"""
        for path in job.aux_files:
            try:
                os.remove(path)
            except OSError:
                pass

    def _emit(self, index, total, job, holder, state):
        total_frames = job.total_frames or 0
        duration = job.duration or 0.0
        out_time = holder["out_time"]
        frame_num = holder.get("frame_num", 0) or 0

        # 进度优先按「已处理帧数 / 预计输出总帧数」计算，但有两个坑必须绕开：
        #   1) 提取音频、单张截图等输出没有视频帧（frame 恒为 0），
        #      只看帧数会让进度条永远停在 0%；
        #   2) 剪辑、改帧率、变速等操作的输出帧数与源文件不同，
        #      只看帧数会算出偏小的百分比（例如 4 秒片段算成 20%）并卡住。
        # 因此两种口径都算，取较大值互相兜底。
        frame_pct = 0.0
        if total_frames > 0 and frame_num > 0:
            frame_pct = min(100.0, (frame_num / total_frames) * 100.0)
        time_pct = 0.0
        if duration > 0:
            time_pct = min(100.0, (out_time / duration) * 100.0)
        pct = max(frame_pct, time_pct)

        # ffmpeg 明确报告 progress=end 时，该任务一定已经完整输出
        if state == "done":
            pct = 100.0

        # 进度只能前进：避免某项指标抖动导致进度条回退
        last_pct = holder.get("pct", 0.0)
        if pct < last_pct:
            pct = last_pct
        holder["pct"] = pct

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
            frame_num=frame_num,
            total_frames=total_frames,
            state=state,
            elapsed=max(0.0, time.time() - holder.get("started", time.time())),
            has_duration=(total_frames > 0 or duration > 0),
        )
        self.on_progress(p)
