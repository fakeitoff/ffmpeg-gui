# -*- coding: utf-8 -*-
"""开发自检脚本：为每个功能页生成真实命令并实际执行，验证端到端可用。

运行：  python selftest.py
"""
from __future__ import annotations

import glob
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from core.probe import locate, probe                      # noqa: E402
from core.runner import Job, JobRunner, Progress          # noqa: E402
from core.util import local_temp_dir, popen_kwargs        # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = ""):
    results.append((label, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label}" + (f"  -> {detail}" if detail else ""))


def make_samples(ffmpeg: str, folder: str):
    """生成测试素材：两段小视频、一张图片、一个字幕。"""
    a = os.path.join(folder, "sample_a.mp4")
    b = os.path.join(folder, "sample_b.mp4")
    logo = os.path.join(folder, "logo.png")
    sub = os.path.join(folder, "sample.srt")

    src = ("testsrc2=size=640x480:rate=30:duration=4", "sine=frequency=440:duration=4")
    for out, freq in ((a, 440), (b, 660)):
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
               "-f", "lavfi", "-i", src[0], "-f", "lavfi", "-i", src[1],
               "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-shortest", out]
        subprocess.run(cmd, check=True, **popen_kwargs())
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=red:size=120x120:d=1",
                    "-frames:v", "1", logo], check=True, **popen_kwargs())
    with open(sub, "w", encoding="utf-8") as fh:
        fh.write("1\n00:00:00,200 --> 00:00:02,500\n测试字幕 Subtitle\n\n")
    return a, b, logo, sub


def main():
    # 自检过程中屏蔽所有弹窗，避免无人值守时卡住
    import tkinter.messagebox as _mb

    _mb.showwarning = lambda *a, **k: None
    _mb.showerror = lambda *a, **k: None
    _mb.showinfo = lambda *a, **k: None
    _mb.askyesno = lambda *a, **k: True

    try:
        ffmpeg, ffprobe = locate()
    except Exception as exc:  # noqa: BLE001
        print(f"找不到 ffmpeg：{exc}")
        return 1
    print(f"ffmpeg = {ffmpeg}\n")

    tmp = tempfile.mkdtemp(prefix="ffgui_test_")
    print(f"测试目录：{tmp}\n")
    a, b, logo, sub = make_samples(ffmpeg, tmp)
    check("生成测试素材", os.path.exists(a) and os.path.exists(b) and os.path.exists(logo))

    # ---- 构造 GUI（隐藏窗口）----
    from ui.app import App

    app = App(initial_files=[a, b])
    app.withdraw()
    app.update()

    app.info = app.get_info(a)
    check("ffprobe 解析源文件", app.info is not None,
          app.info.describe() if app.info else "解析失败")

    for tab in app.tabs:
        tab.on_src_changed()

    def run(label, tab, out_name, extra_setup=None):
        if extra_setup:
            extra_setup()
        src = tab.src_override or a
        dst = os.path.join(tmp, out_name)
        try:
            args = tab.build_cmd(src, dst)
        except Exception as exc:  # noqa: BLE001
            check(label, False, f"构建命令失败：{exc}")
            return
        err = tab.validate()
        if err:
            check(label, False, f"校验未通过：{err}")
            return
        cmd = Job(src, dst, args).command(ffmpeg, "error")
        proc = subprocess.run(cmd, **popen_kwargs())
        is_pattern = "%" in dst
        ok = proc.returncode == 0 and (is_pattern or (os.path.exists(dst) and os.path.getsize(dst) > 0))
        detail = ""
        if ok:
            try:
                info = probe(ffprobe, dst)
                detail = f"{os.path.getsize(dst)} 字节 · {info.describe()}"
            except Exception:
                detail = f"{os.path.getsize(dst)} 字节" if not is_pattern else "序列输出"
        else:
            stderr = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
            detail = stderr[-1] if stderr else f"退出码 {proc.returncode}"
            print("        命令：" + " ".join(cmd))
        check(label, ok, detail)
        tab.cleanup()

    tabs = {type(t).__name__: t for t in app.tabs}

    # ---- 1. 格式转换 ----
    t = tabs["ConvertTab"]
    run("格式转换 mp4(H.264)", t, "01_convert.mp4",
        lambda: (t.fmt.set(t.fmt_cb.cget("values")[0]), t.venc.set("libx264  |  x"),
                 t.aenc.set("aac  |  x"), t.crf.set(28)))
    run("格式转换 → MP3", t, "02_convert.mp3",
        lambda: (t.kind.set("audio"), t._on_kind(),
                 t.fmt.set(t.fmt_cb.cget("values")[0])))

    # ---- 2. 压缩 ----
    t = tabs["CompressTab"]
    run("压缩 480p CRF28", t, "03_compress.mp4",
        lambda: (t.strategy.set("小体积（CRF 28）"), t._on_strategy(),
                 t.resolution.set([r[0] for r in __import__(
                     "ui.tabs.tab_compress", fromlist=["RESOLUTIONS"]).RESOLUTIONS][5]),
                 t._on_resolution()))
    run("压缩 目标体积 0.3MB", t, "04_target.mp4",
        lambda: (t.strategy.set("指定目标体积（MB）"), t._on_strategy(),
                 t.target_mb.set("0.3"), t.resolution.set("640 × 360    (360p)"),
                 t._on_resolution()))

    # ---- 3. 剪辑 ----
    t = tabs["TrimTab"]
    run("剪辑 1s~3s 精确", t, "05_trim.mp4",
        lambda: (t.start.set("00:00:01"), t.dur.set("2"), t.mode.set("accurate")))
    run("剪辑 快速复制", t, "06_trim_fast.mp4",
        lambda: (t.start.set("1"), t.dur.set("2"), t.mode.set("fast")))
    run("剪辑 裁剪+旋转", t, "07_crop.mp4",
        lambda: (t.crop_on.set(True), t.crop_w.set("320"), t.crop_h.set("240"),
                 t.rotation.set("顺时针 90°")))

    # ---- 4. 音频 ----
    t = tabs["AudioTab"]
    run("音频 提取 WAV", t, "08_audio.wav",
        lambda: (t.mode.set("extract"), t._on_mode(),
                 t.fmt.set([v for v in t.fmt_cb.cget("values") if v.startswith("wav")][0]),
                 t.vol_value.set("0.5")))
    run("音频 移除音轨", t, "09_mute.mp4", lambda: (t.mode.set("remove"), t._on_mode()))
    run("音频 替换音轨", t, "10_replace.mp4",
        lambda: (t.mode.set("replace"), t._on_mode(), t.audio_file.set(b)))
    run("音频 混音", t, "11_mix.mp4",
        lambda: (t.mode.set("mix"), t._on_mode(), t.audio_file.set(b), t.bgm_volume.set("0.3")))
    run("音频 响度标准化", t, "12_loudnorm.mp4",
        lambda: (t.mode.set("extract"), t._on_mode(),
                 t.fmt.set([v for v in t.fmt_cb.cget("values") if v.startswith("m4a")][0]),
                 t.loudnorm.set(True)))

    # ---- 5. 特效 ----
    t = tabs["EffectsTab"]
    run("特效 变速 2x（同步变速）", t, "13_speed.mp4",
        lambda: (t.operation.set("变速（快放 / 慢放，声音同步变调不变）"), t._on_operation(),
                 t.speed.set("2.0"), t.audio_mode.set("sync")))
    run("特效 变速 0.5x（保留原音频）", t, "13b_speed_keep.mp4",
        lambda: (t.speed.set("0.5"), t.audio_mode.set("keep")))
    run("特效 变速 3x（丢弃音频）", t, "13c_speed_mute.mp4",
        lambda: (t.speed.set("3.0"), t.audio_mode.set("none")))

    # 变速的音轨校验
    for name, want_audio in (("13_speed.mp4", True),
                             ("13b_speed_keep.mp4", True),
                             ("13c_speed_mute.mp4", False)):
        try:
            sinfo = probe(ffprobe, os.path.join(tmp, name))
            n_audio = sum(1 for s in sinfo.streams if s.type == "audio")
            check(f"{name} 音轨数{'>0' if want_audio else '=0'}",
                  (n_audio > 0) if want_audio else (n_audio == 0),
                  f"{n_audio} 条 · {sinfo.describe()}")
        except Exception as exc:  # noqa: BLE001
            check(f"{name} 音轨校验", False, str(exc))

    # 关键回归：ffprobe 探测结果不可用时（未返回/失败），绝不能据此丢弃音轨
    saved_info = app.info
    try:
        app.info = None
        t.operation.set("变速（快放 / 慢放，声音同步变调不变）")
        t._on_operation()
        t.audio_mode.set("sync")
        args_no_probe = t.build_cmd(a, os.path.join(tmp, "probe_none.mp4"))
        check("探测不可用时变速仍不丢音轨（命令无 -an）",
              "-an" not in args_no_probe, " ".join(args_no_probe))
        t.operation.set("文字水印")
        t._on_operation()
        args_wm = t.build_cmd(a, os.path.join(tmp, "probe_none_wm.mp4"))
        check("探测不可用时水印仍不丢音轨（命令无 -an）",
              "-an" not in args_wm, " ".join(args_wm))
    finally:
        app.info = saved_info

    run("特效 文字水印", t, "14_textwm.mp4",
        lambda: (t.operation.set("文字水印"), t._on_operation(),
                 t.wm_text.set("中文水印: 100% 'ok' [测试]\\n第二行")))
    run("特效 图片水印", t, "15_imgwm.mp4",
        lambda: (t.operation.set("图片水印 / Logo"), t._on_operation(),
                 t.logo_file.set(logo), t.wm_width.set("15")))
    run("特效 画中画", t, "16_pip.mp4",
        lambda: (t.operation.set("画中画（视频叠加视频）"), t._on_operation(),
                 t.logo_file.set(b), t.wm_width.set("40")))
    run("特效 硬字幕", t, "17_burnsub.mp4",
        lambda: (t.operation.set("烧录字幕（硬字幕，永久显示）"), t._on_operation(),
                 t.sub_file.set(sub)))
    run("特效 调色 eq", t, "18_eq.mp4",
        lambda: (t.operation.set("仅调整画面（调色 / 模糊 / 锐化）"), t._on_operation(),
                 t.saturation.set(2.0), t.brightness.set(0.05)))

    # ---- 6. 合并 / 拼接 ----
    t = tabs["MergeTab"]
    run("合并 首尾拼接(直接复制)", t, "30_merge_copy.mp4",
        lambda: (t.operation.set("首尾拼接 · 把多个视频接成一段"), t._on_operation(),
                 t.join_mode.set("copy"), t._on_join_mode()))
    run("合并 首尾拼接(兼容重编码)", t, "31_merge_reencode.mp4",
        lambda: (t.join_mode.set("reencode"), t._on_join_mode(),
                 t.resolution.set("640 × 360    (360p)")))
    run("合并 首尾拼接 + 转场", t, "32_merge_xfade.mp4",
        lambda: (t.transition_on.set(True), t._on_transition(),
                 t.transition.set("fade"), t.transition_dur.set("1.0"),
                 t.resolution.set("跟随第一个视频")))
    run("合并 音视频合并", t, "33_merge_mux.mp4",
        lambda: (t.operation.set("音视频合并 · 画面来自 A，声音来自 B"), t._on_operation(),
                 t.audio_file.set(b), t.mux_aenc.set("aac")))
    run("合并 多音轨封装 MKV", t, "34_merge_tracks.mkv",
        lambda: (t.operation.set("多音轨封装 · 多个文件的音轨合进一个文件"), t._on_operation(),
                 t.extra_list.set_files([b])))
    run("合并 并排同屏(左右)", t, "35_merge_hstack.mp4",
        lambda: (t.operation.set("并排同屏 · 两个视频左右 / 上下同屏"), t._on_operation(),
                 t.side_file.set(b), t.side_layout.set("hstack"),
                 t.side_audio.set("first"), t.side_size.set("640 × 360    (360p)")))
    run("合并 上下堆叠 + 混音", t, "36_merge_vstack.mp4",
        lambda: (t.side_layout.set("vstack"), t.side_audio.set("mix"),
                 t.side_size.set("640 × 360    (360p)")))

    # 拼接的预期时长必须是各段之和（否则进度条百分比算错）
    t.operation.set("首尾拼接 · 把多个视频接成一段")
    t._on_operation()
    t.join_mode.set("copy")
    t._on_join_mode()
    exp_dur = (app.get_info(a).duration or 0) + (app.get_info(b).duration or 0)
    got_dur = t.expected_duration(a)
    check("拼接预期时长 = 各段之和", bool(got_dur) and abs(got_dur - exp_dur) < 0.05,
          f"{got_dur:.2f}s vs {exp_dur:.2f}s")
    exp_frames = (app.get_info(a).video_frames or 0) + (app.get_info(b).video_frames or 0)
    got_frames = t.expected_frames(a)
    check("拼接预期帧数 = 各段帧数之和", got_frames > 0 and abs(got_frames - exp_frames) <= 1,
          f"{got_frames} vs {exp_frames}")

    # 命令行预览稳定性 + 临时文件策略
    t.operation.set("首尾拼接 · 把多个视频接成一段")
    t._on_operation()
    t.join_mode.set("copy")
    t._on_join_mode()
    probe_dst = os.path.join(tmp, "preview_probe.mp4")
    t.build_cmd(a, probe_dst)

    local_temp = local_temp_dir()
    glob_pattern = os.path.join(local_temp, "*")
    before_files = set(glob.glob(glob_pattern))
    cmd_first = t.build_cmd(a, probe_dst)
    for _ in range(8):
        cmd_last = t.build_cmd(a, probe_dst)
    after_files = set(glob.glob(glob_pattern))
    check("拼接命令预览稳定（清单路径不变）", cmd_first == cmd_last, " ".join(cmd_first))
    check("反复生成命令不新增临时文件",
          after_files == before_files and len(after_files) == 1,
          f"{len(before_files)} -> {len(after_files)} 个")
    check("临时文件位于程序目录 temp/ 下（不使用系统盘临时目录）",
          os.path.normcase(local_temp) == os.path.normcase(os.path.join(ROOT, "temp")),
          local_temp)

    e = tabs["EffectsTab"]
    e.operation.set("文字水印")
    e._on_operation()
    e.wm_text.set("中文水印: 100% 'ok' [测试]\n第二行")
    cmd_e = " ".join(e.build_cmd(a, probe_dst))
    wm_files = e.aux_files()
    check("文字水印走 textfile，彻底规避转义问题",
          "textfile='" in cmd_e and ":text='" not in cmd_e,
          cmd_e[cmd_e.find("drawtext"):cmd_e.find("drawtext") + 100])
    check("多行水印 = 每行一个文本文件，且都不含换行",
          len(wm_files) == 2 and all(os.path.exists(p) for p in wm_files)
          and all("\n" not in open(p, encoding="utf-8").read() for p in wm_files),
          f"{len(wm_files)} 个文件")
    check("水印文本原样写入（引号/方括号/冒号/百分号不变形）",
          open(wm_files[0], encoding="utf-8").read() == "中文水印: 100% 'ok' [测试]",
          open(wm_files[0], encoding="utf-8").read())
    e.cleanup()
    check("cleanup 后水印文本文件已删除", not any(os.path.exists(p) for p in wm_files))

    # 合并结果校验
    try:
        info_copy = probe(ffprobe, os.path.join(tmp, "30_merge_copy.mp4"))
        check("直接拼接总时长 ≈ 8 秒", 7.5 < info_copy.duration < 8.6,
              f"{info_copy.duration:.2f} 秒 · {info_copy.describe()}")
    except Exception as exc:  # noqa: BLE001
        check("直接拼接总时长 ≈ 8 秒", False, str(exc))
    try:
        info_x = probe(ffprobe, os.path.join(tmp, "32_merge_xfade.mp4"))
        check("转场拼接总时长 ≈ 7 秒", 6.5 < info_x.duration < 7.6,
              f"{info_x.duration:.2f} 秒")
    except Exception as exc:  # noqa: BLE001
        check("转场拼接总时长 ≈ 7 秒", False, str(exc))
    try:
        info_s = probe(ffprobe, os.path.join(tmp, "35_merge_hstack.mp4"))
        res = f"{info_s.video.width}x{info_s.video.height}" if info_s.video else "?"
        # 源为 640x480，统一高度 360 后每路 480x360，左右并排 => 960x360
        check("并排后画面宽度翻倍 (960x360)", res == "960x360", res)
    except Exception as exc:  # noqa: BLE001
        check("并排后画面宽度翻倍 (960x360)", False, str(exc))
    try:
        info_t = probe(ffprobe, os.path.join(tmp, "34_merge_tracks.mkv"))
        check("多音轨封装含 2 条音轨",
              sum(1 for s in info_t.streams if s.type == "audio") == 2,
              " / ".join(s.summary() for s in info_t.streams))
    except Exception as exc:  # noqa: BLE001
        check("多音轨封装含 2 条音轨", False, str(exc))

    # ---- 7. 截图 ----
    t = tabs["CaptureTab"]
    run("截图 单帧", t, "20_frame.jpg",
        lambda: (t.mode.set("单张截图（指定时间点抽一帧）"), t._on_mode(), t.time.set("2")))
    run("截图 缩略图拼图", t, "21_tile.jpg",
        lambda: (t.mode.set("缩略图拼图（一张网格总览图）"), t._on_mode(),
                 t.tile_cols.set("3"), t.tile_rows.set("2"), t.interval.set("0.5")))
    run("截图 预览 GIF", t, "22_preview.gif",
        lambda: (t.mode.set("预览动图（导出 GIF 片段）"), t._on_mode(),
                 t.gif_start.set("0"), t.gif_dur.set("1.5")))

    # ---- 8. 批量截图 ----
    t = tabs["CaptureTab"]
    run("截图 批量(序列输出)", t, "23_shots_%04d.jpg",
        lambda: (t.mode.set("批量截图（按间隔抽取多张）"), t._on_mode(),
                 t.interval.set("1"), t.max_count.set("3")))
    seq_ok = all(os.path.exists(os.path.join(tmp, f"23_shots_{i:04d}.jpg")) for i in (1, 2, 3))
    check("批量截图 生成 3 张序列", seq_ok)

    # ---- 9. 自定义命令 ----
    t = tabs["CustomTab"]
    run("自定义命令（默认模板）", t, "24_custom.mp4",
        lambda: t.text.delete("1.0", "end") or t.text.insert("1.0", __import__(
            "ui.tabs.tab_custom", fromlist=["TEMPLATE"]).TEMPLATE))
    run("自定义命令（GIF 片段）", t, "25_custom.gif",
        lambda: (t.ext.set("gif"),
                 t.text.delete("1.0", "end") or t.text.insert(
                     "1.0", '-ss 0 -t 1 -i {input} -vf "fps=10,scale=320:-1:flags=lanczos,'
                            'split[a][b];[a]palettegen[p];[b][p]paletteuse" -loop 0 {output}')))

    # ---- 10. 自定义命令解析 ----
    tokens = t._tokens()
    joined = " ".join(tokens)
    check("自定义命令解析含引号参数",
          "fps=10,scale=320:-1:flags=lanczos" in joined and "palettegen" in joined,
          str(tokens[5:8]))

    # ---- 11. 媒体信息页 ----
    info_tab = tabs["InfoTab"]
    info_tab.on_src_changed()
    content = info_tab.text.get("1.0", "end")
    check("媒体信息页输出", "分辨率" in content and "编码" in content,
          content.splitlines()[1] if content.splitlines() else "")

    # ---- 12. 执行流程与界面状态 ----
    # 回归点：JobRunner 曾把停止信号命名为 self._stop，覆盖了
    # threading.Thread._stop()，导致线程结束后 is_alive() 抛 TypeError，
    # 表现为「命令行预览一直停在『正在执行…』」且窗口关不掉。
    import time as _time

    def pump(seconds):
        end = _time.time() + seconds
        while _time.time() < end:
            app.update()
            _time.sleep(0.02)

    app.notebook.select(1)              # 压缩 / 画质（会真实重新编码）
    app._on_tab_changed()
    # 把任务调得慢一些，保证「执行中」状态能被预览轮询稳定观察到
    ct = app.tabs[1]
    ct.strategy.set("均衡（CRF 23，推荐）")
    ct._on_strategy()
    ct.preset.set("slow")
    ct.resolution.set("1920 × 1080  (1080p)")
    ct._on_resolution()
    pump(0.6)
    check("runner 状态查询不抛异常", app._runner_busy() in (True, False))

    def run_cycle(tag):
        app.on_start()
        seen_running = False
        deadline = _time.time() + 90
        while _time.time() < deadline:
            pump(0.15)
            if app._last_preview.startswith("正在执行"):
                seen_running = True
            if app.runner.results:
                break
        pump(0.4)

        def preview_back():
            pv = app._last_preview
            return bool(pv) and "ffmpeg" in pv.lower() and not pv.startswith("正在")

        recovery = _time.time() + 6
        while _time.time() < recovery and not preview_back():
            pump(0.15)

        all_ok = bool(app.runner.results) and all(r[1] for r in app.runner.results)
        check(f"第 {tag} 次执行：过程中显示「正在执行」", seen_running)
        check(f"第 {tag} 次执行：任务全部成功（{len(app.runner.results)} 个）", all_ok)
        check(f"第 {tag} 次执行：runner 已结束", app._runner_busy() is False)
        check(f"第 {tag} 次执行：预览恢复为真实命令行", preview_back(),
              app._last_preview[:64])
        check(f"第 {tag} 次执行：开始按钮恢复可用",
              str(app.btn_start.cget("state")) == "normal")

    run_cycle(1)
    run_cycle(2)

    # ---- 12b. 进度条行为（回归：曾「一直 0% 不动」）----
    # 1) 时长已知：进度条数值必须随进度变化，并显示百分比/已用时
    app._reset_progress()
    app._apply_progress(Progress(job_total=1, percent=0.0, overall=0.0, has_duration=True))
    v0 = float(app.progress.cget("value"))
    app._apply_progress(Progress(job_total=1, percent=42.0, overall=42.0, has_duration=True,
                                 out_time=12.0, elapsed=3.0, speed="2.0x"))
    v1 = float(app.progress.cget("value"))
    check("时长已知：进度条随进度变化", v0 == 0 and abs(v1 - 42.0) < 0.01, f"{v0} → {v1}")
    check("时长已知：显示百分比", app.percent_text.get() == "42.0%", app.percent_text.get())
    check("时长已知：状态栏含已用时", "已用时" in app.status_text.get(), app.status_text.get())
    # 2) 时长未知：必须退化为滚动动画，不能冻在 0%
    app._apply_progress(Progress(job_total=1, percent=0.0, has_duration=False, elapsed=2.0))
    check("时长未知：切换为滚动动画", str(app.progress.cget("mode")) == "indeterminate",
          str(app.progress.cget("mode")))
    check("时长未知：显示「处理中」", app.percent_text.get() == "处理中", app.percent_text.get())
    app._reset_progress()
    check("重置后回到确定模式", str(app.progress.cget("mode")) == "determinate")

    # 按实际处理帧数算进度的计算逻辑（直接验证 _emit）
    rec = []
    _jr = JobRunner([], ffmpeg, on_progress=lambda p: rec.append(p))
    _jr._emit(0, 1,
              Job(a, os.path.join(tmp, "frame_probe.mp4"), [], duration=10.0, total_frames=100),
              {"out_time": 5.0, "speed": "", "fps": "", "frame": "50", "frame_num": 50,
               "size": "", "started": time.time()}, "running")
    check("按帧算进度：50/100 帧 → 50%", rec and abs(rec[-1].percent - 50.0) < 0.01,
          f"{rec[-1].percent:.1f}%" if rec else "无回调")
    check("Progress 携带帧数信息", rec and rec[-1].frame_num == 50 and rec[-1].total_frames == 100,
          f"{rec[-1].frame_num}/{rec[-1].total_frames}" if rec else "")
    # 帧数未知时退回按时间估算
    rec.clear()
    _jr._emit(0, 1,
              Job(a, os.path.join(tmp, "t.mp4"), [], duration=10.0, total_frames=0),
              {"out_time": 5.0, "speed": "", "fps": "", "frame": "0", "frame_num": 0,
               "size": "", "started": time.time()}, "running")
    check("帧数未知时退回按时间估算：5s/10s → 50%", rec and abs(rec[-1].percent - 50.0) < 0.01,
          f"{rec[-1].percent:.1f}%" if rec else "无回调")

    # ---- 13. 布局检查：同一格子（列区间相交）里不能有两个控件 ----
    # 回归点：自定义命令页曾手工推算 grid 行号，导致「常用参数片段」按钮网格
    # 与「输出」标题叠在同一行，界面被切断。
    def layout_overlaps():
        bad = []
        for tab in app.tabs:
            holder = getattr(tab, "form_holder", None)
            if holder is None:
                continue
            rows: dict[int, list] = {}
            for child in holder.winfo_children():
                info = child.grid_info()
                if not info:
                    continue
                row = int(info.get("row", 0))
                col = int(info.get("column", 0))
                span = max(1, int(info.get("columnspan", 1)))
                rows.setdefault(row, []).append((col, col + span - 1, child.winfo_class()))
            for row, items in rows.items():
                for i in range(len(items)):
                    for j in range(i + 1, len(items)):
                        a, b = items[i], items[j]
                        if a[0] <= b[1] and b[0] <= a[1]:
                            bad.append(f"{tab.name} 第{row}行 {a[2]}与{b[2]}")
        return bad

    overlaps = layout_overlaps()
    check("各功能页布局无控件重叠", not overlaps,
          "; ".join(overlaps[:3]) if overlaps else f"{len(app.tabs)} 个页面全部正常")

    # ---- 14. 关闭窗口（内部会 destroy，之后不再使用 app）----
    close_error = ""
    try:
        app._on_close()
    except Exception as exc:  # noqa: BLE001
        close_error = str(exc)
    check("窗口可正常关闭（含关闭时的临时文件清理）", not close_error, close_error)

    # ---- 清理测试残留 ----
    import shutil

    shutil.rmtree(tmp, ignore_errors=True)

    # ---- 汇总 ----
    print("\n" + "=" * 70)
    passed = sum(1 for _l, ok, _d in results if ok)
    print(f"通过 {passed} / {len(results)}")
    for label, ok, detail in results:
        if not ok:
            print(f"  失败：{label}  {detail}")
    print("=" * 70)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
