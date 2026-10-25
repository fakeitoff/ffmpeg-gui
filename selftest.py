# -*- coding: utf-8 -*-
"""开发自检脚本：为每个功能页生成真实命令并实际执行，验证端到端可用。

运行：  python selftest.py
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from core import probe as probe_mod                     # noqa: E402
from core.probe import locate, probe                    # noqa: E402
from core.runner import Job, JobRunner, Progress          # noqa: E402
from core.util import (is_http_url, local_temp_dir, popen_kwargs, url_stem)        # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = ""):
    results.append((label, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label}" + (f"  -> {detail}" if detail else ""))


def make_samples(ffmpeg: str, folder: str):
    """生成测试素材：两段小视频、一张图片、一个字幕、一个内嵌 mov_text 字幕的 MP4。"""
    a = os.path.join(folder, "sample_a.mp4")
    b = os.path.join(folder, "sample_b.mp4")
    logo = os.path.join(folder, "logo.png")
    sub = os.path.join(folder, "sample.srt")
    subbed = os.path.join(folder, "sample_sub.mp4")

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
    # 网上下载的 MP4 常见「内嵌 mov_text 字幕」，直接 -c copy 进 MKV 会整批失败，
    # 专门做一份这种素材来回归字幕流的编码处理。
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-i", a, "-i", sub, "-map", "0", "-map", "1",
                    "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text", subbed],
                   check=True, **popen_kwargs())
    return a, b, logo, sub, subbed


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

    # 测试素材同样只写程序目录的 temp/ 下（不碰系统盘临时目录）；
    # 用唯一子目录避免多次运行互相踩，跑完删除，万一崩溃则由程序启动时
    # 按 12 小时年龄回收 temp/ 里的遗留物。
    scratch_root = local_temp_dir()
    tmp = tempfile.mkdtemp(prefix="ffgui_test_", dir=scratch_root)
    print(f"测试目录：{tmp}\n")
    a, b, logo, sub, subbed = make_samples(ffmpeg, tmp)
    check("生成测试素材", os.path.exists(a) and os.path.exists(b) and os.path.exists(logo)
          and os.path.exists(subbed))

    # ---- 构造 GUI（隐藏窗口）----
    from ui.app import App

    # 日志与偏好也落在程序 temp/ 的素材目录里，不污染仓库的 log/ 与 settings.json
    log_dir = os.path.join(tmp, "log")
    settings_file = os.path.join(tmp, "settings.json")
    app = App(initial_files=[a, b], log_dir=log_dir, settings_file=settings_file)
    app.withdraw()
    app.update()

    app.info = app.get_info(a)
    check("ffprobe 解析源文件", app.info is not None,
          app.info.describe() if app.info else "解析失败")

    # ---- 1b. 运行日志实时落盘（排查问题用的就是它）----
    def log_text():
        try:
            with open(app.run_log.path, encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError as exc:
            return f"(读不到日志：{exc})"

    check("启动即建日志文件，并在界面上告诉用户在哪",
          app.run_log.enabled and os.path.isfile(app.run_log.path)
          and os.path.normcase(os.path.dirname(app.run_log.path)) == os.path.normcase(log_dir),
          app.run_log.path)
    head = log_text()
    check("日志开头记录环境信息（时间/Python/命令行/ffmpeg 路径与版本）",
          "启动时间" in head and "命令行" in head and "ffmpeg" in head
          and "Python" in head, head.splitlines()[1][:90] if len(head.splitlines()) > 1 else head)
    # 「实时」是本节的重点：不 close、不批量刷，写完就得在文件里
    marker = f"实时落盘测试 {time.time():.6f}"
    app.log(marker, "info")
    check("每条日志立刻能在文件里读到（未 flush 到界面、未关窗）",
          marker in log_text(), marker)
    app.log("http://host/x.m3u8?sign=SECRETSIGN&t=9 带签名地址", "cmd")
    body = log_text()
    check("在线地址的签名参数落盘前被抹掉",
          "SECRETSIGN" not in body and "参数已隐藏" in body and "x.m3u8" in body,
          [ln for ln in body.splitlines() if "x.m3u8" in ln][-1][:110])
    stale = os.path.join(log_dir, "run-19700101-000000.log")
    with open(stale, "w", encoding="utf-8") as fh:
        fh.write("旧日志\n")
    os.utime(stale, (time.time() - 40 * 86400, time.time() - 40 * 86400))
    keeper = os.path.join(log_dir, "run-20991231-000000.log")
    with open(keeper, "w", encoding="utf-8") as fh:
        fh.write("新日志\n")
    from core.logfile import RunLog as _RL

    _RL(directory=log_dir)
    check("旧日志按 30 天自动回收，新的留着（且只认 run-*.log）",
          not os.path.exists(stale) and os.path.exists(keeper),
          f"{stale} 已删 / {keeper} 保留")
    os.remove(keeper)

    # 排障最需要的就是失败当场的 ffmpeg 原话，逐条经 app.log 转写进文件
    fail_job = Job(a, os.path.join(tmp, "log_fail.mp4"),
                   ["-i", "missing_asset_for_log.xyz", "-c", "copy"])
    JobRunner([fail_job], ffmpeg, overwrite=True,
              on_log=lambda line, kind="info": app.log(line, kind)).run()
    err_body = log_text()
    check("真实失败的 ffmpeg 报错原样进日志（命令与报错都在）",
          "missing_asset_for_log.xyz" in err_body
          and "No such file" in err_body and "$ " in err_body,
          [ln for ln in err_body.splitlines() if "No such file" in ln][-1][:110])

    # ---- 12a. 探测健壮性：文件名编码与无元数据的媒体 ----
    # 回归点 1：ffprobe 输出 UTF-8 JSON，而 Windows 中文环境默认 GBK。
    # 未显式指定 encoding 时，文件名含中文/《》/emoji 会让解码在读取线程里
    # 抛异常，stdout 变空后被当成「空信息」（时长/帧数全 0），
    # 于是进度条退化成「处理中」动画。
    import shutil
    weird = os.path.join(tmp, "《书名号》中文🎬测试.mp4")
    try:
        shutil.copyfile(a, weird)
        winfo = probe(ffprobe, weird)
        check("文件名含《》/中文/emoji 仍能解析出时长与帧数",
              winfo is not None and winfo.duration > 0 and winfo.video_frames > 0,
              f"时长={winfo.duration:.2f}s 帧数={winfo.video_frames}" if winfo else "解析失败")
    except Exception as exc:  # noqa: BLE001
        check("文件名含《》/中文/emoji 仍能解析出时长与帧数", False, str(exc))

    # 回归点 2：H.264/HEVC 裸流、单张图片既不写 nb_frames 也读不到 duration，
    # 必须靠 -count_packets 兜底，否则压缩页只能显示「处理中」。
    raw = os.path.join(tmp, "raw_stream.h264")
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-i", a, "-c:v", "copy", "-bsf:v", "h264_mp4toannexb",
                    "-an", raw], check=True, **popen_kwargs())
    try:
        rinfo = probe(ffprobe, raw)
        check("H.264 裸流也能算出总帧数（包数兜底）",
              rinfo is not None and rinfo.video_frames > 0,
              f"帧数={rinfo.video_frames} 时长={rinfo.duration:.2f}s" if rinfo else "解析失败")
    except Exception as exc:  # noqa: BLE001
        check("H.264 裸流也能算出总帧数（包数兜底）", False, str(exc))

    try:
        iinfo = probe(ffprobe, logo)
        check("单张图片也能算出帧数（包数兜底）",
              iinfo is not None and iinfo.video_frames > 0,
              f"帧数={iinfo.video_frames}" if iinfo else "解析失败")
    except Exception as exc:  # noqa: BLE001
        check("单张图片也能算出帧数（包数兜底）", False, str(exc))

    # 能力清单解析：ffmpeg 的 -encoders / -filters 输出前面有一段说明行
    # （"V..... = Video"、"T.. = Timeline support"），旧解析把它们也当成了条目，
    # 集合里因此混进 "="；能力判断虽然目前只用于「有没有某个名字」，
    # 但脏数据会让「列出全部编码器」这类功能一加就出错。
    from core.probe import available_encoders, available_filters

    enc_set = available_encoders(ffmpeg)
    flt_set = available_filters(ffmpeg)
    junk = {x for x in enc_set | flt_set if not x[0].isalpha()}
    check("编码器/滤镜清单不含说明行脏数据",
          not junk and "=" not in (enc_set | flt_set),
          f"脏数据={sorted(junk)[:5]}")
    check("能力清单仍能识别常用编码器与滤镜",
          {"libx264", "aac", "gif"} <= enc_set and {"drawtext", "xfade", "tile"} <= flt_set,
          f"{len(enc_set)} 个编码器 / {len(flt_set)} 个滤镜")

    for tab in app.tabs:
        tab.on_src_changed()

    def run(label, tab, out_name, extra_setup=None, src=None):
        if extra_setup:
            extra_setup()
        src = src or tab.src_override or a
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

    # 回归：MP4 内嵌字幕是 mov_text，MKV 不认它。原来一律 -c copy，
    # 勾选「保留全部音轨与字幕」转 MKV 会在写头时整批失败。
    app.src_files = [subbed]
    app._refresh_src_list()
    app.info = app.get_info(subbed)
    for tab in app.tabs:
        tab.on_src_changed()
    t = tabs["ConvertTab"]
    t.kind.set("video")
    t._on_kind()
    mkv_value = next(v for v in t.fmt_cb.cget("values") if v.strip().startswith("mkv"))
    t.fmt.set(mkv_value)
    t._on_format()
    t.venc.set("copy  |  直接复制（不重新编码）")
    t.aenc.set("copy  |  直接复制（不重新编码）")
    t.keep_all.set(True)
    keep_dst = os.path.join(tmp, "02b_keepall.mkv")
    args_ka = t.build_cmd(subbed, keep_dst)
    check("保留全部流时给 mov_text 字幕指定目标编码",
          "-c:s:0" in args_ka and "ass" in args_ka, " ".join(args_ka))
    run("格式转换 保留全部流 → MKV", t, "02b_keepall.mkv", src=subbed)
    try:
        ka_info = probe(ffprobe, keep_dst)
        n_sub = sum(1 for s in ka_info.streams if s.type == "subtitle")
        check("MKV 里字幕流被保留（转成了 ass）", n_sub == 1,
              " / ".join(f"#{s.index} {s.type} {s.codec}" for s in ka_info.streams))
    except Exception as exc:  # noqa: BLE001
        check("MKV 里字幕流被保留（转成了 ass）", False, str(exc))
    t.keep_all.set(False)
    # 后续用例仍以 sample_a 作为主源文件
    app.src_files = [a, b]
    app._refresh_src_list()
    app.info = app.get_info(a)
    for tab in app.tabs:
        tab.on_src_changed()

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

    # 回归：「等比缩放」原来输出的是 scale=W:H，ffmpeg 会把画面强行拉成 W×H，
    # 与「拉伸」毫无区别（640x480 → 640x360 被压扁）。现在必须保持比例。
    run("压缩 等比缩放 640×360", t, "04b_fit.mp4",
        lambda: (t.strategy.set("均衡（CRF 23，推荐）"), t._on_strategy(),
                 t.resolution.set("640 × 360    (360p)"), t._on_resolution(),
                 t.scale_mode.set("fit  |  等比缩放（保持比例，尺寸自适应）"),
                 t.audio_mode.set("copy  |  直接复制")))
    try:
        fit_info = probe(ffprobe, os.path.join(tmp, "04b_fit.mp4"))
        fit_res = f"{fit_info.video.width}x{fit_info.video.height}"
        # 640x480(4:3) 放进 640x360(16:9) 的框内 → 480x360，且不能等于框的尺寸
        check("等比缩放保持宽高比（640x480 → 480x360）", fit_res == "480x360", fit_res)
    except Exception as exc:  # noqa: BLE001
        check("等比缩放保持宽高比（640x480 → 480x360）", False, str(exc))

    # 回归：目标体积要按**当前文件**的时长算码率。原来读的是第一个文件的
    # 探测结果，批量时每个文件都被按同一条码率压；探测失败还会静默退回 CRF。
    saved_info = app.info
    t.strategy.set("指定目标体积（MB）")
    t._on_strategy()
    t.target_mb.set("1")
    t.audio_mode.set("none  |  移除音频")
    t._on_audio()
    app.info = None                       # 模拟第一个文件探测失败
    br_batch = t._resolve_bitrate(a)      # 4 秒 → 1MB ≈ 2097k
    check("目标体积按当前文件时长算码率",
          bool(br_batch) and abs(float(br_batch.rstrip("k")) - 2097.15) < 60,
          str(br_batch))
    app.info = saved_info
    t.strategy.set("均衡（CRF 23，推荐）")
    t._on_strategy()
    t.audio_mode.set("copy  |  直接复制")
    t._on_audio()

    # ---- 3. 剪辑 ----
    t = tabs["TrimTab"]
    run("剪辑 1s~3s 精确", t, "05_trim.mp4",
        lambda: (t.start.set("00:00:01"), t.dur.set("2"), t.mode.set("accurate")))
    run("剪辑 快速复制", t, "06_trim_fast.mp4",
        lambda: (t.start.set("1"), t.dur.set("2"), t.mode.set("fast")))
    run("剪辑 裁剪+旋转", t, "07_crop.mp4",
        lambda: (t.crop_on.set(True), t.crop_w.set("320"), t.crop_h.set("240"),
                 t.rotation.set("顺时针 90°")))

    # 新增：淡入淡出（画面 + 声音），且淡出位置按**截取后**的片段长度算
    run("剪辑 1s~3s + 淡入淡出", t, "07b_fade.mp4",
        lambda: (t.crop_on.set(False), t.rotation.set("不旋转"), t.angle.set("0"),
                 t.start.set("1"), t.dur.set("2"), t.mode.set("accurate"),
                 t.fade_in.set("0.5"), t.fade_out.set("0.5")))
    fade_cmd = " ".join(t.build_cmd(a, os.path.join(tmp, "07b_fade.mp4")))
    check("淡入淡出同时作用于画面与声音",
          "fade=t=in" in fade_cmd and "fade=t=out" in fade_cmd
          and "afade=t=in" in fade_cmd and "afade=t=out" in fade_cmd, fade_cmd[-90:])
    check("淡出起点按截取后的片段长度算（2 秒片段 - 0.5 秒 = 1.5 秒）",
          "st=1.5:d=0.5" in fade_cmd, fade_cmd[-90:])
    t.fade_in.set("3")
    t.fade_out.set("3")
    fade_err = t.validate()
    check("淡入淡出总长超过片段长度会被拦下", bool(fade_err), str(fade_err))
    t.fade_in.set("")
    t.fade_out.set("")

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
    # amix 默认会把每条输入按比例衰减，混完背景音后原声明显变轻。
    # 新版 ffmpeg 可关（normalize=0），老版本没这个选项、写了会报错 —— 按能力拼。
    mix_cmd = " ".join(t.build_cmd(a, os.path.join(tmp, "11b_mix_probe.mp4")))
    want_norm = probe_mod.filter_has_option(ffmpeg, "amix", "normalize")
    check("混音按 ffmpeg 版本能力决定是否加 normalize=0",
          (":normalize=0" in mix_cmd) == want_norm, mix_cmd[:130])
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
    # 回归：「小窗宽度 40%」是相对**主视频**。原来写成 scale=iw*0.4，
    # iw 是叠加素材自己的宽度 —— 拿 120px 的图叠 640px 视频只得到 48px 小窗。
    t.logo_file.set(logo)
    t.wm_width.set("40")
    pip_cmd = " ".join(t.build_cmd(a, os.path.join(tmp, "16b_pip_probe.mp4")))
    check("画中画小窗按主视频宽度缩放（640 的 40% = 256）",
          "scale=256:-2" in pip_cmd, pip_cmd[pip_cmd.find("-filter_complex"):][:70])
    t.logo_file.set(b)
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
    # 回归：界面上写「所有音轨与字幕都会复制进来」，但原来只映射 :a?，
    # 附加文件里的 .srt/.ass 被静默丢掉。
    run("合并 多音轨封装（含字幕）", t, "34b_merge_sub.mkv",
        lambda: t.extra_list.set_files([sub]))
    try:
        mt_info = probe(ffprobe, os.path.join(tmp, "34b_merge_sub.mkv"))
        n_sub = sum(1 for s in mt_info.streams if s.type == "subtitle")
        check("多音轨封装把附加字幕也带进去了", n_sub == 1,
              " / ".join(f"#{s.index} {s.type_cn} {s.codec}" for s in mt_info.streams))
    except Exception as exc:  # noqa: BLE001
        check("多音轨封装把附加字幕也带进去了", False, str(exc))
    t.extra_list.clear()
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
    # 只数文件：测试素材此刻就放在 temp/ 的子目录里，不应被算成「新增的临时文件」
    def temp_files():
        return {p for p in glob.glob(glob_pattern) if os.path.isfile(p)}

    before_files = temp_files()
    cmd_first = t.build_cmd(a, probe_dst)
    for _ in range(8):
        cmd_last = t.build_cmd(a, probe_dst)
    after_files = temp_files()
    check("拼接命令预览稳定（清单路径不变）", cmd_first == cmd_last, " ".join(cmd_first))
    check("反复生成命令不新增临时文件",
          after_files == before_files and len(after_files) == 1,
          f"{len(before_files)} -> {len(after_files)} 个 · " +
          "、".join(os.path.basename(p) for p in sorted(after_files)))
    check("临时文件位于程序目录 temp/ 下（不使用系统盘临时目录）",
          os.path.normcase(local_temp) == os.path.normcase(os.path.join(ROOT, "temp")),
          local_temp)
    check("自检素材目录也在程序 temp/ 之下",
          os.path.normcase(os.path.abspath(tmp)).startswith(
              os.path.normcase(os.path.abspath(local_temp)) + os.sep),
          tmp)

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

    # ---- 6b. m3u8 合成（下载站的「播放列表 + 分片」变成一个视频）----
    t = tabs["MergeTab"]
    hls_dir = os.path.join(tmp, "hls")
    os.makedirs(hls_dir, exist_ok=True)
    playlist = os.path.join(hls_dir, "test.m3u8")
    # 必须真切成多片：x264 默认 GOP 远长于素材，不强制关键帧时 -hls_time 1
    # 也只有一个分片，跨分片拼接根本没被测到。
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", a,
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-force_key_frames", "expr:gte(t,n_forced*1)", "-c:a", "aac",
                    "-hls_time", "1", "-hls_list_size", "0",
                    "-hls_segment_filename", os.path.join(hls_dir, "seg%d.ts"),
                    playlist], check=True, **popen_kwargs())
    segs = sorted(glob.glob(os.path.join(hls_dir, "seg*.ts")))
    rep = probe_mod.playlist_report(playlist)
    check("m3u8 识别 + 分片清点",
          probe_mod.is_hls_playlist(playlist) and len(segs) >= 2
          and rep["segments"] == len(segs) and not rep["missing"],
          f"磁盘 {len(segs)} 片 / 报告 {rep['segments']} 片")
    try:
        hinfo = probe(ffprobe, playlist)
        check("ffprobe 读 m3u8 能拿到时长与帧数（进度条依赖它）",
              hinfo.has_video and hinfo.duration > 3 and hinfo.video_frames > 0,
              f"{hinfo.duration:.2f}s {hinfo.video_frames} 帧")
    except Exception as exc:  # noqa: BLE001
        check("ffprobe 读 m3u8 能拿到时长与帧数（进度条依赖它）", False, str(exc))

    t.operation.set("m3u8 合成 · 播放列表 / 分片合成一个视频")
    t._on_operation()
    t.hls_mode.set("copy")
    t._on_hls_mode()
    t.container.set("保持原格式")
    app.src_files = [playlist]
    app._refresh_src_list()
    app.info = app.get_info(playlist)
    cmd_h = t.build_cmd(playlist, os.path.join(tmp, "shape.mp4"))
    check("HLS 输入参数排在 -i 之前，且不手写 -bsf:a（音频非 AAC 时会打不开输出）",
          cmd_h.index("-protocol_whitelist") < cmd_h.index("-i")
          and "-allowed_extensions" in cmd_h and "-bsf:a" not in cmd_h,
          " ".join(cmd_h[:8]))
    check("m3u8 的「保持原格式」不会输出 .m3u8 文件", t.output_ext() == "mp4",
          t.output_ext())
    run("m3u8 直接合成 → MP4", t, "37_hls_copy.mp4", src=playlist)
    try:
        hc = probe(ffprobe, os.path.join(tmp, "37_hls_copy.mp4"))
        check("合成结果时长≈源且音视频流俱全",
              3.5 < hc.duration < 4.8 and hc.has_video and hc.has_audio,
              f"{hc.duration:.2f}s · {hc.describe()}")
    except Exception as exc:  # noqa: BLE001
        check("合成结果时长≈源且音视频流俱全", False, str(exc))

    # 分片没下全是最常见的失败，必须提前点名缺了谁
    lonely_dir = os.path.join(tmp, "lonely")
    os.makedirs(lonely_dir, exist_ok=True)
    lonely = os.path.join(lonely_dir, "test.m3u8")
    shutil.copyfile(playlist, lonely)
    app.src_files = [lonely]
    miss_err = t.validate()
    check("分片缺失时报错点名缺失文件", bool(miss_err) and "seg0.ts" in miss_err,
          str(miss_err).replace("\n", " / "))
    app.src_files = [a]
    wrong_err = t.validate()
    check("第一个文件不是 m3u8 时给出可操作的提示",
          bool(wrong_err) and "首尾拼接" in wrong_err, str(wrong_err).replace("\n", " / "))
    os.remove(lonely)
    os.rmdir(lonely_dir)

    # AES-128 加密分片：密钥文件通常叫 *.key，不在 ffmpeg 默认的扩展名白名单里，
    # 不加 -allowed_extensions ALL 会直接失败（实测）。
    key = os.path.join(hls_dir, "enc.key")
    with open(key, "wb") as fh:
        fh.write(bytes(range(16)))
    kinfo = os.path.join(hls_dir, "kinfo.txt")
    with open(kinfo, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("enc.key\n" + key.replace("\\", "/") + "\n")
    eplaylist = os.path.join(hls_dir, "enc.m3u8")
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", a,
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-force_key_frames", "expr:gte(t,n_forced*1)", "-c:a", "aac",
                    "-hls_time", "1", "-hls_list_size", "0", "-hls_key_info_file", kinfo,
                    "-hls_segment_filename", os.path.join(hls_dir, "enc%d.ts"), eplaylist],
                   check=True, **popen_kwargs())
    erep = probe_mod.playlist_report(eplaylist)
    check("加密列表同样点清分片与密钥", erep["segments"] >= 2 and not erep["missing"],
          f"{erep['segments']} 片，缺失 {erep['missing_total']}")
    app.src_files = [eplaylist]
    app.info = app.get_info(eplaylist)
    run("m3u8 合成 AES-128 加密分片", t, "38_hls_enc.mp4", src=eplaylist)
    os.remove(key)
    app.src_files = [eplaylist]
    key_err = t.validate()
    check("密钥文件丢失时提前点名", bool(key_err) and "enc.key" in key_err,
          str(key_err).replace("\n", " / "))
    with open(key, "wb") as fh:
        fh.write(bytes(range(16)))

    t.hls_mode.set("reencode")
    t._on_hls_mode()
    t.venc.set("libx264")
    t.crf.set("30")
    t.preset.set("ultrafast")
    t.aenc.set("aac")
    app.src_files = [playlist]
    run("m3u8 兼容合成（重新编码）", t, "39_hls_reencode.mp4", src=playlist)
    t.hls_mode.set("copy")
    t._on_hls_mode()
    t.container.set("保持原格式")

    app.src_files = [a, b]
    app._refresh_src_list()
    app.info = app.get_info(a)
    for tab in app.tabs:
        tab.on_src_changed()

    # ---- 6c. 在线 m3u8：下载 / 录制直播（本地起 http 服务，不外连）----
    import http.server
    import socket as _socket
    import threading as _threading

    serve_dir = os.path.join(tmp, "web")
    os.makedirs(os.path.join(serve_dir, "vod"), exist_ok=True)
    UA_TAG = "ffgui-selftest"
    hits: list[tuple[str, str]] = []

    class _Gate(http.server.BaseHTTPRequestHandler):
        """只放行带测试 UA 的请求：403 / 200 的差别正是 User-Agent 参数存在的理由。"""

        def do_GET(self):
            hits.append((self.path, self.headers.get("User-Agent", "")))
            if UA_TAG not in self.headers.get("User-Agent", ""):
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"denied")
                return
            full = os.path.join(serve_dir, self.path.split("?")[0].lstrip("/").replace("/", os.sep))
            if not os.path.isfile(full):
                self.send_response(404)
                self.end_headers()
                return
            data = open(full, "rb").read()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    _sk = _socket.socket()
    _sk.bind(("127.0.0.1", 0))
    PORT = _sk.getsockname()[1]
    _sk.close()
    web = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), _Gate)
    _threading.Thread(target=web.serve_forever, daemon=True).start()

    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", a,
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-force_key_frames", "expr:gte(t,n_forced*1)", "-c:a", "aac",
                    "-hls_time", "1", "-hls_list_size", "0",
                    "-hls_segment_filename", os.path.join(serve_dir, "vod", "v%d.ts"),
                    os.path.join(serve_dir, "vod", "index.m3u8")],
                   check=True, **popen_kwargs())
    URL = f"http://127.0.0.1:{PORT}/vod/index.m3u8?sign=abc123&t=2"

    local_only = probe_mod.hls_input_args(playlist)
    net_only = probe_mod.hls_input_args(URL, UA_TAG, "http://127.0.0.1")
    check("网络参数只给在线地址（本地列表带上会 Option not found）",
          "-reconnect" not in local_only and "-user_agent" not in local_only
          and all(k in net_only for k in ("-reconnect", "-user_agent", "-referer",
                                          "-protocol_whitelist", "-allowed_extensions")),
          " ".join(net_only[:10]))
    check("带 ?签名 的在线地址仍认成播放列表，文件名不含签名",
          probe_mod.is_hls_playlist(URL) and is_http_url(URL)
          and url_stem(URL) == "index" and "sign" not in url_stem(URL), url_stem(URL))
    check("非 http(s) 前缀的地址被拒", not is_http_url("file:///C:/x.m3u8")
          and not is_http_url("crypto://x") and is_http_url("HTTPS://h/a.m3u8"))
    check("本地文件名里的 ? 不会被当成查询串（Linux 下它是合法字符）",
          probe_mod.is_hls_playlist("/tmp/a?.m3u8") and not probe_mod.is_hls_playlist("/tmp/a.txt"))

    no_ua = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error",
                            *probe_mod.HLS_BASE_ARGS, "-i", URL, "-c", "copy", "-y",
                            os.path.join(tmp, "no_ua.mkv")], **popen_kwargs())
    check("不带 UA 会被服务端 403 拒绝（证明这个参数不是摆设）",
          no_ua.returncode != 0 and b"403" in (no_ua.stderr or b""),
          ((no_ua.stderr or b"").decode("utf-8", "replace").strip().splitlines() or [""])[-1][:90])

    t = tabs["MergeTab"]
    app.notebook.select(app.tabs.index(t))    # 落点显示只看「当前页」，得先切到合并页
    app._on_tab_changed()
    t.container.set("保持原格式")
    t.operation.set("m3u8 合成 · 播放列表 / 分片合成一个视频")
    t._on_operation()
    check("本地 m3u8 不劫持容器（仍是「保持原格式」）",
          t.container.get() == "保持原格式", t.container.get())
    t.hls_url.set(URL)                     # 这一填要自动把容器和落点亮出来
    t.hls_ua.set(UA_TAG)
    t.hls_refer.set("http://127.0.0.1/")
    t.hls_record.set("")
    check("填了在线地址自动选中 mkv（实测只有它支持边下边播、被硬杀也能播）",
          t.container.get() == "mkv", t.container.get())
    check("顶部「输出位置」随地址自动更新，不用用户去找落点",
          app.out_path.get().endswith("index_merged.mkv")
          and "将保存到" in str(app.out_hint.cget("text")),
          f"{app.out_path.get()} ｜ {str(app.out_hint.cget('text'))[:40]}")
    err = t.validate()
    check("在线地址通过校验", err is None, str(err))
    dl_dir = os.path.join(tmp, "dl")
    os.makedirs(dl_dir, exist_ok=True)
    _mode_before, _path_before = app.out_mode.get(), app.out_path.get()
    app.out_mode.set("custom")
    app.out_path.set(dl_dir)
    remote_dst = app._remote_output(t, URL)
    check("在线地址的输出用地址里最后一段命名，落到指定目录",
          os.path.normcase(os.path.dirname(remote_dst)) == os.path.normcase(dl_dir)
          and os.path.basename(remote_dst) == "index_merged.mkv", remote_dst)
    # 默认落点 downloads/ 是「不存在就要建出来」的目录：曾经把目录路径传给
    # ensure_dir（它建的是文件的父目录），结果 downloads/ 从来没被创建过
    import ui.app as ui_app

    _root_before = ui_app.APP_ROOT
    ui_app.APP_ROOT = tmp
    app.out_mode.set("auto")
    app.out_path.set("")
    auto_dst = app._remote_output(t, URL)
    ui_app.APP_ROOT = _root_before
    app.out_mode.set("custom")
    app.out_path.set(dl_dir)
    check("在线地址的默认落点目录会被真的创建",
          os.path.isdir(os.path.dirname(auto_dst))
          and os.path.normcase(os.path.dirname(auto_dst))
          == os.path.normcase(os.path.join(tmp, "downloads")), auto_dst)
    t.container.set("保持原格式")
    check("在线地址的「保持原格式」默认给 mkv（边下边播 + 抗硬杀）",
          t.output_ext() == "mkv", t.output_ext())
    t.container.set("mkv")

    run("在线 m3u8 下载到 MKV", t, "40_web_dl.mkv", src=URL)
    try:
        dinfo = probe(ffprobe, os.path.join(tmp, "40_web_dl.mkv"))
        check("在线下载产物时长与音视频流俱全",
              3.4 < dinfo.duration < 5.0 and dinfo.has_video and dinfo.has_audio,
              f"{dinfo.duration:.2f}s · {dinfo.describe()}")
    except Exception as exc:  # noqa: BLE001
        check("在线下载产物时长与音视频流俱全", False, str(exc))
    vod_hits = [p for p, ua in hits if p.startswith("/vod/") and UA_TAG in ua]
    check("分片请求确实带着 UA 发出（点播列表 + 各分片都覆盖到）",
          len(vod_hits) >= 3, f"{len(vod_hits)} 个请求")
    # 走界面自己的「开始处理」再下一遍：命令行、ffmpeg 输出、日志落盘是同一条路
    t.hls_record.set("3")
    app.notebook.select(app.tabs.index(t))
    app._on_tab_changed()
    app.overwrite.set(True)
    app.on_start()
    deadline = time.time() + 90
    while time.time() < deadline and not (app.runner and app.runner.results):
        app.update()
        time.sleep(0.05)
    app.update()
    job_results = list(app.runner.results) if app.runner else []
    check("界面「开始处理」的在线下载真的跑完",
          bool(job_results) and job_results[0][1] is True, str(job_results[:1])[:110])
    real_out = job_results[0][0] if job_results else ""
    check("产物落在指定的下载目录里",
          os.path.isfile(real_out) and os.path.getsize(real_out) > 1000, real_out)
    # 结束消息走的是界面队列，比 results 晚一拍到；等到它进了日志再判
    settle = time.time() + 10
    while time.time() < settle:
        body = log_text()
        if "完成" in body or "已手动停止" in body:
            break
        app.update()
        time.sleep(0.05)
    line_with_url = [ln for ln in body.splitlines() if "vod/index.m3u8" in ln]
    check("真实流程的日志能回溯命令行，且签名参数不落地",
          bool(line_with_url) and "参数已隐藏" in line_with_url[-1]
          and "sign=abc123" not in body,
          line_with_url[-1][-80:] if line_with_url else "(日志里没有该命令行)")
    check("日志里能看到 ffmpeg 的结束报告",
          "完成" in body or "已手动停止" in body,
          body.rstrip().splitlines()[-1][:80] if body.strip() else "(空)")
    t.hls_record.set("")

    t.hls_reconnect.set("5")
    cmd_r = t.build_cmd(URL, os.path.join(tmp, "shape_r.mkv"))
    check("重连参数按用户填的退避秒数下发（reconnect + streamed + delay_max）",
          cmd_r[cmd_r.index("-reconnect") + 1] == "1"
          and cmd_r[cmd_r.index("-reconnect_streamed") + 1] == "1"
          and cmd_r[cmd_r.index("-reconnect_delay_max") + 1] == "5",
          " ".join(cmd_r[:14]))
    t.hls_reconnect.set("")
    cmd_d = t.build_cmd(URL, os.path.join(tmp, "shape_d.mkv"))
    check("重连等待留空走默认 30 秒",
          cmd_d[cmd_d.index("-reconnect_delay_max") + 1]
          == str(probe_mod.HLS_RECONNECT_DEFAULT),
          cmd_d[cmd_d.index("-reconnect_delay_max") + 1])
    rerr_bad = []
    for value in ("0", "-3", "abc", "99999"):
        t.hls_reconnect.set(value)
        msg = t.validate() or ""
        if "重连" not in msg:
            rerr_bad.append(f"{value}→{msg[:26]}")
    t.hls_reconnect.set("")
    check("非法重连等待（0 / 负数 / 非数字 / 超上限）都被拦下", not rerr_bad,
          "; ".join(rerr_bad))

    t.hls_record.set("2")
    cmd_t = t.build_cmd(URL, os.path.join(tmp, "shape_t.mkv"))
    check("填了录制时长就带 -t（到点自停）",
          "-t" in cmd_t and cmd_t[cmd_t.index("-t") + 1] == "2", " ".join(cmd_t[:6]))
    check("录制时长就是预期时长（进度条按它算百分比）",
          abs((t.expected_duration(URL) or 0) - 2.0) < 0.01,
          f"{t.expected_duration(URL)}")
    t.hls_record.set("abc")
    bad_rec = t.validate()
    check("录制时长填非数字时提前拦下", bool(bad_rec) and "正数" in bad_rec, str(bad_rec))
    t.hls_record.set("")
    check("没填录制时长按「随时可停」处理，不谎报百分比",
          t.expected_duration(URL) is None and t.expected_frames(URL) == 0,
          str(t.expected_duration(URL)))
    t.hls_record.set("2")
    run("在线 m3u8 只录 2 秒", t, "41_web_rec2.mkv", src=URL)
    try:
        rinfo = probe(ffprobe, os.path.join(tmp, "41_web_rec2.mkv"))
        check("录制 2 秒的产物确实约 2 秒", 1.4 < rinfo.duration < 3.2,
              f"{rinfo.duration:.2f}s")
    except Exception as exc:  # noqa: BLE001
        check("录制 2 秒的产物确实约 2 秒", False, str(exc))
    t.hls_record.set("")

    t.hls_url.set("ftp://host/a.m3u8")
    check("非 http(s) 地址在校验里被拒", "http" in str(t.validate()), str(t.validate()))
    t.hls_url.set("http://host/notalist?x=1")
    check("认不出播放列表扩展名的地址给出明确提示",
          "m3u8" in str(t.validate()), str(t.validate()))
    t.hls_url.set(URL)

    # ---- 边下边播 + 手动停止（用 -re 限速的本地长任务，不依赖网络时序）----
    long_src = os.path.join(tmp, "long30.mp4")
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=30",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", long_src], check=True, **popen_kwargs())

    def grow_probe(dst):
        return subprocess.run([ffprobe, "-v", "error", "-show_entries", "stream=codec_type",
                               "-of", "csv=p=0", dst], **popen_kwargs()).returncode

    mid = {}
    stop_msg = {}
    stop_result = {}
    for dst in (os.path.join(tmp, "42_grow.mkv"), os.path.join(tmp, "42_grow.mp4")):
        args = ["-re", "-i", long_src, "-c", "copy"]
        if dst.endswith(".mp4"):
            args += ["-movflags", "+faststart"]
        args += [dst]
        msgs: list[str] = []
        jr = JobRunner([Job(long_src, dst, args, duration=30.0)], ffmpeg, overwrite=True,
                       on_finished=lambda ok, msg, _m=msgs: _m.append(msg))
        jr.start()
        deadline = time.time() + 20
        while time.time() < deadline and (not os.path.exists(dst)
                                         or os.path.getsize(dst) < 30000):
            time.sleep(0.1)
        mid[dst] = (grow_probe(dst), os.path.getsize(dst) if os.path.exists(dst) else 0)
        jr.cancel()                       # 走 UI 上「停止」按钮那条路
        jr.join(timeout=25)
        stop_msg[dst] = msgs[0] if msgs else "(没有结束回调)"
        stop_result[dst] = list(jr.results)

    mkv_mid, mp4_mid = mid[os.path.join(tmp, "42_grow.mkv")], mid[os.path.join(tmp, "42_grow.mp4")]
    check("边下边播：mkv 还在写就能打开", mkv_mid[0] == 0 and mkv_mid[1] > 0,
          f"打开rc={mkv_mid[0]} 已写 {mkv_mid[1]} 字节")
    check("边下边播：mp4 没写完打不开（所以直播默认给 mkv）",
          mp4_mid[0] != 0, f"打开rc={mp4_mid[0]} 已写 {mp4_mid[1]} 字节")
    mkv_out = os.path.join(tmp, "42_grow.mkv")
    check("点「停止」后已录的部分不会被删掉", os.path.isfile(mkv_out)
          and os.path.getsize(mkv_out) > 0, f"{os.path.getsize(mkv_out)} 字节")
    mkv_agg = stop_msg[mkv_out]
    mkv_per = stop_result[mkv_out][0][2] if stop_result[mkv_out] else "(无结果)"
    check("停止的措辞区分「录完」与「我停了」：汇总说已停止、单任务说已保存",
          "已停止" in mkv_agg and "已手动停止" in mkv_per, f"{mkv_agg} ｜ {mkv_per}")
    try:
        ginfo = probe(ffprobe, mkv_out)
        check("手动停止的录像完整可解码", ginfo.duration > 1 and ginfo.has_video,
              f"{ginfo.duration:.2f}s · {ginfo.describe()}")
    except Exception as exc:  # noqa: BLE001
        check("手动停止的录像完整可解码", False, str(exc))
    mp4_out = os.path.join(tmp, "42_grow.mp4")
    mp4_per = stop_result[mp4_out][0][2] if stop_result[mp4_out] else "(无结果)"
    check("mp4 靠优雅收尾也能保住（送 q 后写完 moov）",
          grow_probe(mp4_out) == 0 and "已手动停止" in mp4_per,
          f"打开rc={grow_probe(mp4_out)} ｜ {mp4_per} ｜ "
          f"{os.path.getsize(mp4_out) if os.path.exists(mp4_out) else 0} 字节")

    web.shutdown()
    app.out_mode.set(_mode_before)
    app.out_path.set(_path_before)
    t.hls_url.set("")
    check("清空在线地址后，自动选的 mkv 还原成「保持原格式」",
          t.container.get() == "保持原格式", t.container.get())
    t.hls_url.set(URL)
    t.container.set("mp4")                 # 用户显式改过
    t.operation.set("首尾拼接 · 把多个视频接成一段")
    t._on_operation()
    check("用户显式选过的容器不会被自动逻辑改回去",
          t.container.get() == "mp4", t.container.get())
    t.hls_url.set("")
    t.hls_ua.set("")
    t.hls_refer.set("")
    t.container.set("保持原格式")
    for tab in app.tabs:
        tab.on_src_changed()

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

    # 回归：时间填到结尾之后 / 拼图格子多于素材长度时，ffmpeg 一帧都不出，
    # 用户只能看到「输出文件未生成或为空」，猜不到是参数问题。现在提前拦下。
    t.mode.set("单张截图（指定时间点抽一帧）")
    t._on_mode()
    t.time.set("99")
    frame_err = t.validate()
    check("截图时间超出视频长度时提前报错", bool(frame_err) and "超出" in frame_err, str(frame_err))
    t.time.set("2")
    t.mode.set("缩略图拼图（一张网格总览图）")
    t._on_mode()
    t.tile_cols.set("6")
    t.tile_rows.set("6")
    t.interval.set("5")
    tile_err = t.validate()
    check("拼图格子多于素材长度时提前报错", bool(tile_err) and "最多只够" in tile_err,
          str(tile_err))

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

    # ---- 12a-pre. 批量执行的容错与界面细节 ----
    # 回归：批量任务里一个文件失败原来会直接中断整批，剩下的文件一个都不处理，
    # 而日志里只留最后那一条错误。
    bad = Job(a, os.path.join(tmp, "batch_bad.mp4"),
              ["-i", os.path.join(tmp, "根本没有这个文件.mp4"),
               os.path.join(tmp, "batch_bad.mp4")])
    good = Job(a, os.path.join(tmp, "batch_good.mp4"),
               ["-i", a, "-c", "copy", os.path.join(tmp, "batch_good.mp4")])
    finished = []
    runner = JobRunner([bad, good], ffmpeg, overwrite=True,
                       on_log=lambda line, kind="info": None,
                       on_finished=lambda ok, msg: finished.append((ok, msg)))
    runner.run()
    check("批量任务：一个失败也继续跑完剩下的",
          len(runner.results) == 2 and runner.results[-1][1] is True,
          str([(r[1], r[2][:30]) for r in runner.results]))
    check("批量任务：汇总里报告失败数量",
          bool(finished) and finished[0][0] is False and "失败 1" in finished[0][1],
          finished[0][1] if finished else "")

    # 失败留下的 0 字节产物会被误认为「已经输出了」，必须清掉；有内容的文件不能动
    empty_out = os.path.join(tmp, "empty_leftover.mp4")
    with open(empty_out, "wb"):
        pass
    JobRunner._drop_empty_output(Job(a, empty_out, []))
    kept_out = os.path.join(tmp, "kept.mp4")
    with open(kept_out, "wb") as fh:
        fh.write(b"x")
    JobRunner._drop_empty_output(Job(a, kept_out, []))
    check("失败任务的 0 字节产物被清理，非空文件保留",
          not os.path.exists(empty_out) and os.path.exists(kept_out))

    # 多选整段移动：选中 C、D 上移应得到 A、C、D、B（逐个交换会把 C、D 顺序换错）
    app.src_files = [a, b, logo, sub]
    app._refresh_src_list()
    app.src_list.selection_clear(0, "end")
    app.src_list.selection_set(2)
    app.src_list.selection_set(3)
    app._move_selected(-1)
    check("多选整段上移保持段内顺序",
          app.src_files == [a, logo, sub, b],
          [os.path.basename(p) for p in app.src_files])
    app.src_files = [a, b]
    app._refresh_src_list()
    app.info = app.get_info(a)

    # 预览必须与真实执行一致：取消勾选「覆盖」时命令里是 -n
    app.notebook.select(0)
    app._on_tab_changed()
    app.overwrite.set(False)
    app._last_preview = ""
    app._refresh_preview_text()
    check("预览随「不覆盖同名文件」切换为 -n", " -n " in app._last_preview,
          app._last_preview[:70])
    app.overwrite.set(True)

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

        # ttk 把「指针掠过按钮」也报成 active，所以判可点击 = 不是 disabled
        def btn_ready():
            return str(app.btn_start.cget("state")) != "disabled"

        # runner 线程是先写 results、再把 finished 投进队列的：中途有一瞬
        # 「线程已结束 + 预览已恢复」但按钮还没被 finished 点亮，
        # 所以两项都要等到位为止，不能只等预览。
        recovery = _time.time() + 6
        while _time.time() < recovery and not (preview_back() and btn_ready()):
            pump(0.15)

        all_ok = bool(app.runner.results) and all(r[1] for r in app.runner.results)
        check(f"第 {tag} 次执行：过程中显示「正在执行」", seen_running)
        check(f"第 {tag} 次执行：任务全部成功（{len(app.runner.results)} 个）", all_ok)
        check(f"第 {tag} 次执行：runner 已结束", app._runner_busy() is False)
        check(f"第 {tag} 次执行：预览恢复为真实命令行", preview_back(),
              app._last_preview[:64])
        check(f"第 {tag} 次执行：开始按钮恢复可用", btn_ready(),
              str(app.btn_start.cget("state")))

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

    # ---- 12c. 进度口径回归：帧数与时间取较大值，且进度只进不退 ----
    # 回归点 1：剪辑/改帧率/变速后，输出帧数小于源帧数，
    #           只按帧算会得出偏小百分比（如 4 秒片段算成 20%）并卡住。
    #           此时应改用时间口径，让进度正常到 100%。
    rec.clear()
    _jr._emit(0, 1,
              Job(a, os.path.join(tmp, "trim_probe.mp4"), [], duration=4.0, total_frames=120),
              {"out_time": 3.6, "speed": "", "fps": "", "frame": "108", "frame_num": 108,
               "size": "", "started": time.time()}, "running")
    check("剪辑场景：帧口径 90% 与时间口径 90% 取较大值 → 90%",
          rec and abs(rec[-1].percent - 90.0) < 0.01,
          f"{rec[-1].percent:.1f}%" if rec else "无回调")
    # 关键判别用例：帧数口径明显偏小（120/600 = 20%），
    # 旧实现会停在 20%；新实现取时间口径 60%。
    rec.clear()
    _jr._emit(0, 1,
              Job(a, os.path.join(tmp, "trim_probe3.mp4"), [], duration=10.0, total_frames=600),
              {"out_time": 6.0, "speed": "", "fps": "", "frame": "120", "frame_num": 120,
               "size": "", "started": time.time()}, "running")
    check("剪辑场景：帧口径偏小(20%)时改用时间口径 → 60%",
          rec and abs(rec[-1].percent - 60.0) < 0.01,
          f"{rec[-1].percent:.1f}%（旧实现会停在 20%）" if rec else "无回调")
    # 时间已经走完但帧数还差一截时，必须取较大值而不是被帧数拖住
    rec.clear()
    _jr._emit(0, 1,
              Job(a, os.path.join(tmp, "trim_probe2.mp4"), [], duration=4.0, total_frames=600),
              {"out_time": 4.0, "speed": "", "fps": "", "frame": "120", "frame_num": 120,
               "size": "", "started": time.time()}, "running")
    check("剪辑场景：帧口径只有 20% 时时间口径兜底 → 100%",
          rec and abs(rec[-1].percent - 100.0) < 0.01,
          f"{rec[-1].percent:.1f}%" if rec else "无回调")

    # 回归点 2：纯音频提取时 frame 恒为 0，只能靠时间口径，不能停在 0%。
    rec.clear()
    _jr._emit(0, 1,
              Job(a, os.path.join(tmp, "audio_probe.m4a"), [], duration=20.0, total_frames=0),
              {"out_time": 10.0, "speed": "", "fps": "", "frame": "0", "frame_num": 0,
               "size": "", "started": time.time()}, "running")
    check("纯音频提取：无视频帧时按时间推进 → 50%",
          rec and abs(rec[-1].percent - 50.0) < 0.01,
          f"{rec[-1].percent:.1f}%" if rec else "无回调")

    # 回归点 3：ffmpeg 报告 progress=end 时必须收到 100%，
    #           否则进度条会在最后几帧停住。
    rec.clear()
    _jr._emit(0, 1,
              Job(a, os.path.join(tmp, "end_probe.mp4"), [], duration=4.0, total_frames=120),
              {"out_time": 3.9, "speed": "", "fps": "", "frame": "115", "frame_num": 115,
               "size": "", "started": time.time()}, "done")
    check("progress=end 时进度直接置 100%",
          rec and abs(rec[-1].percent - 100.0) < 0.01,
          f"{rec[-1].percent:.1f}%" if rec else "无回调")

    # 回归点 4：进度只能前进，某项指标抖动不得让进度条回退。
    rec.clear()
    _holder = {"out_time": 8.0, "speed": "", "fps": "", "frame": "240", "frame_num": 240,
               "size": "", "started": time.time(), "pct": 0.0}
    _job = Job(a, os.path.join(tmp, "mono_probe.mp4"), [], duration=10.0, total_frames=300)
    _jr._emit(0, 1, _job, _holder, "running")      # 80%
    _holder["out_time"], _holder["frame_num"] = 2.0, 60   # 人为回退
    _jr._emit(0, 1, _job, _holder, "running")
    check("进度不回退：指标抖动后仍保持 80%",
          len(rec) == 2 and abs(rec[-1].percent - 80.0) < 0.01,
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

    # 合并页每个操作一块参数区，上面的检查看不到区内的排版；
    # 而且 grid_remove 的隐藏块仍然带着 grid_info，所以只看「已映射」的控件。
    mt = tabs["MergeTab"]
    mt.operation.set("m3u8 合成 · 播放列表 / 分片合成一个视频")
    mt._on_operation()
    hls_bad = []
    for mode in ("copy", "reencode"):
        mt.hls_mode.set(mode)
        mt._on_hls_mode()
        app.update()
        rows: dict[int, list] = {}
        for child in mt.hls_box.winfo_children():
            if not child.winfo_ismapped():
                continue
            gi = child.grid_info()
            col = int(gi.get("column", 0))
            rows.setdefault(int(gi.get("row", 0)), []).append(
                (col, col + max(1, int(gi.get("columnspan", 1))) - 1, child.winfo_class()))
        for row, items in rows.items():
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    if items[i][0] <= items[j][1] and items[j][0] <= items[i][1]:
                        hls_bad.append(f"{mode} 第{row}行 {items[i][2]}与{items[j][2]}")
    check("m3u8 参数区两种合成方式下排版都不重叠", not hls_bad,
          "; ".join(hls_bad[:3]) if hls_bad else "copy / reencode 均正常")

    # ---- 13b. 顶部高度、折叠与偏好记忆（用户抱怨「每次都要手动拖」）----
    s = app.ui_scale
    app.update_idletasks()
    open_h = app.card.winfo_reqheight()
    check("顶部默认高度封顶，不再吃掉大半屏", open_h <= 150 * s,
          f"{open_h}px（上限 {int(150 * s)}px，缩放 {s:.2f}）")
    app._toggle_card()
    app.update_idletasks()
    shut_h = app.card.winfo_reqheight()
    check("顶部能一键折叠，折叠后只剩一两行", shut_h * 2 < open_h,
          f"{open_h}px → {shut_h}px")
    app._toggle_card()
    app.update_idletasks()
    check("展开后恢复原来的高度", app.card.winfo_reqheight() > shut_h,
          f"{shut_h}px → {app.card.winfo_reqheight()}px")
    check("折叠时头部那行仍能看出文件数与输出目标",
          "源文件 2 个" in app._card_head.get() and "→" in app._card_head.get(),
          app._card_head.get())
    check("正文用封顶滚动容器，超出可以滚轮看",
          type(app.card_body).__name__ == "VScrollBox"
          and int(str(app.card_body.canvas.cget("height"))) <= app.card_body.max_height,
          f"canvas={app.card_body.canvas.cget('height')} ≤ {app.card_body.max_height}")
    frac = app._current_sash_fraction()
    check("分隔条默认位置给日志留出空间（不超过约 0.6）", 0.3 <= frac <= 0.6, str(frac))
    for raw, want in (("0.75", 0.75), ("5", 0.85), ("0.01", 0.30), ("坏值", 0.56)):
        app._prefs["sash"] = raw
        got = app._sash_fraction()
        if abs(got - want) > 1e-6:
            break
    check("偏好里的分隔条位置被采用，异常值夹回安全范围",
          abs(got - want) <= 1e-6, f"{raw} → {got}")
    app._prefs["sash"] = 0.56
    app._prefs["geometry"] = "99999x99999+50000+50000"
    geo = app._initial_geometry()
    m = re.match(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$", geo)
    check("旧屏幕上记住的尺寸换屏后会被夹回屏内（不会出现拖不回来的窗口）",
          bool(m) and int(m.group(1)) <= app.winfo_screenwidth()
          and int(m.group(3)) <= app.winfo_screenwidth() - 100, geo)
    app._prefs["geometry"] = ""
    app._save_prefs()
    from core import settings as settings_mod

    saved = settings_mod.load(settings_file)
    check("关闭时记住窗口尺寸 / 分隔条位置 / 顶部折叠状态",
          {"geometry", "sash", "card_open"} <= set(saved)
          and saved["sash"] == app._current_sash_fraction(), str(sorted(saved)))
    with open(settings_file, "w", encoding="utf-8") as fh:
        fh.write("{ 这不是合法 JSON")
    check("偏好文件坏了也只当没有偏好，不影响使用",
          settings_mod.load(settings_file) == {})

    # ---- 14. 关闭窗口（内部会 destroy，之后不再使用 app）----
    close_error = ""
    try:
        app._on_close()
    except Exception as exc:  # noqa: BLE001
        close_error = str(exc)
    check("窗口可正常关闭（含关闭时的临时文件清理）", not close_error, close_error)
    end_text = log_text()
    check("关窗后日志留在文件里，并以「窗口关闭」收尾",
          os.path.isfile(app.run_log.path) and end_text.rstrip().endswith("窗口关闭"),
          (end_text.rstrip().splitlines() or [""])[-1][:90])
    # 关窗后 temp/ 里不该留下任何本次运行的痕迹（改名预览产生的清单尤其容易漏）
    leftovers = [os.path.basename(p) for p in glob.glob(glob_pattern)
                 if os.path.isfile(p)]
    check("关闭后程序 temp/ 不残留本次产生的临时文件", not leftovers,
          "、".join(leftovers[:4]))

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
