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

# --------------------------------------------------------------------------
# 网络直播源的日志分类
# --------------------------------------------------------------------------
# 直播源会把复用的连接重置掉（WSAECONNRESET / -10054），ffmpeg 自己换条连接重取，
# 这类「正在自愈」的行原来按关键词判会被标成红色错误，真正的失败反而不显眼。
# 下面的串都是在 ffmpeg 8.1 可执行文件里核对过的，不是凭印象写的。
RETRY_HINTS = ("retrying with new connection", "keepalive request failed", "will reconnect")
LOSS_HINTS = ("segment not found", "failed to open segment", "does not contain any stream")
# 源把坏数据直接喂进来了（实测出现在 bilibili 的 AV1 直播流里：
# 「Failed to read unit 1 (type 3): Invalid data found」+「Failed to parse temporal unit」）。
# 这类不体现为 hls 层「取不到分片」，只数分片会漏掉，必须单独统计。
DAMAGE_HINTS = ("invalid data found", "failed to parse", "failed to read unit",
                "error while decoding", "corrupt")
# 传输层噪声：本身不算丢内容，也不值得红色
NOISE_HINTS = ("error in the push function", "error number -10054",
               "connection reset by peer", "input/output error")


def net_activity(line: str) -> str:
    """把一行 ffmpeg 日志判为 ``"skip"`` / ``"damage"`` / ``"retry"`` / ``""``。

    丢内容的判断优先，避免「Found duplicated MOOV Atom. Skipped it」这种
    正常提示被算成丢了一段——它只是把重复的 init 头丢掉，画面一个字节没少。
    """
    low = str(line).lower()
    if any(h in low for h in LOSS_HINTS):
        return "skip"
    if any(h in low for h in DAMAGE_HINTS):
        return "damage"
    if any(h in low for h in RETRY_HINTS):
        return "retry"
    return ""


def is_transient_noise(line: str) -> bool:
    """重连过程中的传输层报错：黄色提示即可，不必标红。"""
    low = str(line).lower()
    return any(h in low for h in NOISE_HINTS)


def network_note(retries: int = 0, lost: int = 0, corrupt: int = 0, lag: float = 0.0,
                 base: float = 0.0, force: bool = False, recorded: float = 0.0,
                 wall: float = 0.0) -> str:
    """把这次网络录制的健康状况压成一句人话。

    ``force``（直播 / 时长未知的任务）时即使一切正常也要出一行：用户按了停止之后
    「什么都没出现」会被当成「这功能没生效」，这里需要一份明确的「没问题」回执。
    落后多少才算问题不能只看绝对值——建连 + 拉播放列表本来就要吃掉一两秒，
    录一小时也还是这一两秒，按固定秒数判会让每次正常停止都冒「疑似缺」，
    所以门槛取 ``max(2 秒, 预期的 1.5%)``。
    """
    from .util import format_time

    parts = []
    if force:
        parts.append(f"已录 {format_time(recorded, 1)} / 实际用时 {format_time(wall, 1)}")
    if lag and lag > max(2.0, (base or 0.0) * 0.015):
        parts.append(f"媒体时间比预期少 {format_time(lag, 1)}")
    if lost:
        parts.append(f"疑似丢失 {lost} 段")
    if corrupt:
        parts.append(f"源数据损坏 {corrupt} 处")
    if retries:
        parts.append(f"重连 {retries} 次（已自动接上）")
    return " · ".join(parts)


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
        # 这里一律读 proc.returncode，不调 proc.poll()：wait() 由 runner 线程
        # 持有，UI 线程再去 waitpid 会把子进程状态抢走（POSIX 上会打乱 wait()）。
        if not proc or proc.returncode is not None:
            return
        # 先礼貌地让它自己收尾：向 ffmpeg 的 stdin 送一个 "q"，它会像按了 q
        # 一样退出并写完文件尾。实测 mp4 / mkv / ts 都因此 rc=0 正常收尾，
        # 而直接 terminate() 会让 mp4 缺 moov 整段报废（直播录到一半点停止
        # 恰恰是最常见的用法），所以这一步不能省。
        if self._quit_gracefully(proc):
            return
        try:
            proc.terminate()
        except Exception:
            pass
        for _ in range(20):
            if proc.returncode is not None:
                break
            time.sleep(0.05)
        if proc.returncode is None:
            try:
                proc.kill()
            except Exception:
                pass

    @staticmethod
    def _quit_gracefully(proc, wait_seconds: float = 10.0) -> bool:
        """请求 ffmpeg 自行退出，等 runner 线程把 returncode 填上。"""
        try:
            proc.stdin.write("q\n")
            proc.stdin.flush()
        except Exception:
            return False       # 没有 stdin（探测用的子进程等），走硬杀
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if proc.returncode is not None:
                return True
            time.sleep(0.1)
        return False

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
        # 用户按过「停止」，这一批的结论就该是「已停止」而不是「完成」：
        # 直播录制到点停止时 ffmpeg 是收到 q 后 rc=0 正常退出的，
        # 只有在汇总这一层才区分得开「录完了」和「录到一半我停了」。
        cancelled = cancelled or self._stop_event.is_set()
        if cancelled:
            ok_all = False
            left = total - len(self.results)
            # 优雅停止留下的产物要正面说出来，别让人以为「取消了 = 白跑了」
            message = f"已停止：已保存 {done} 个" if done else "已停止：没有可用产物"
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
                bufsize=1,
                # stdin 要留着：取消时向它送一个 "q" 让 ffmpeg 自己收尾
                # （DEVNULL 就只能硬杀，mp4 会缺 moov）
                **popen_kwargs(stdin=subprocess.PIPE),
            )
        except OSError as exc:
            return False, f"无法启动 ffmpeg：{exc}"

        with self._lock:
            self._proc = proc

        errors: list[str] = []
        progress_holder = {
            "out_time": 0.0, "speed": "", "fps": "", "frame": "", "frame_num": 0,
            "size": "", "started": time.time(), "pct": 0.0,
            "retry": 0, "lost": 0, "corrupt": 0,
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
                    act = net_activity(line)
                    if act == "retry":
                        # 正在自愈（换连接重取同一片）：黄色提示，而且**不能**进 errors，
                        # 否则一次普通的连接重置会被当成失败原因贴到最终报告里。
                        progress_holder["retry"] += 1
                        self.on_log(line, "warn")
                    elif act == "skip":
                        progress_holder["lost"] += 1
                        errors.append(line)
                        self.on_log(line, "error")
                    elif act == "damage":
                        # 源直接喂进来了坏数据（AV1/HEVC 直播流实测）：不体现在
                        # 「取不到分片」上，只数分片就会漏，所以单独计一项。
                        progress_holder["corrupt"] += 1
                        errors.append(line)
                        self.on_log(line, "error")
                    elif is_transient_noise(line):
                        self.on_log(line, "warn")
                    elif "error" in low or "invalid" in low or "failed" in low or "no such" in low:
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

        # 「这次到底缺没缺」用客观量判断，不靠人读日志：
        # 知道预期时长的（点播、填了录制时长的直播）拿预期比，
        # 不知道的用墙钟比 —— 但只在「按实时前进」的源上才这么算，
        # 否则一个 0.3x 的慢转码会被误报成落后一堆。
        def lag_and_base() -> tuple[float, float]:
            media = progress_holder["out_time"]
            if job.duration and job.duration > 0:
                return float(job.duration) - media, float(job.duration)
            speed = str(progress_holder["speed"] or "").rstrip("xX").strip()
            try:
                if speed and float(speed) > 1.5:
                    return 0.0, 0.0
            except ValueError:
                pass
            wall = time.time() - progress_holder["started"]
            return wall - media, wall

        media = progress_holder["out_time"]
        wall = time.time() - progress_holder["started"]
        # 时长未知的任务（直播、探测失败）默认也要出一行：用户按了停止之后
        # 「什么都没出现」会被读成「这功能没生效」，得给一份「没问题」的回执。
        unknown = not (job.duration and job.duration > 0)
        lag, base = lag_and_base()
        note = network_note(retries=progress_holder["retry"], lost=progress_holder["lost"],
                            corrupt=progress_holder["corrupt"], lag=lag, base=base,
                            force=unknown, recorded=media, wall=wall)
        if note:
            level = "error" if (progress_holder["lost"] or progress_holder["corrupt"]) \
                else ("warn" if (progress_holder["retry"] or lag > max(2.0, base * 0.015))
                      else "info")
            self.on_log(f"网络统计：{note}", level)

        if self._stop_event.is_set():
            # 「停止」是用户主动按的，已经写下的部分就是他要的成品
            # （录直播最常见的收尾方式）。ffmpeg 收到 q 会正常写完文件尾并返回 0，
            # 这种产物必须留下；只有收尾失败（被强杀）的半成品才删掉——
            # 否则磁盘上躺着一只打不开的 mp4，比什么都不留更容易误导人。
            from .util import human_size

            size = os.path.getsize(job.dst) if os.path.isfile(job.dst) else 0
            if rc == 0 and size > 0:
                return True, (f"已手动停止 · 已保存 {human_size(size)}"
                              + (f"（{note}）" if note else ""))
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
        return True, "完成" + (f"（{note}）" if note else "")

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
