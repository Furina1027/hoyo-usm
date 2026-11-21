"""无损导出管线：解密 → 封装（全部 codec copy）→ 校验 → 批量与报告。

封装矩阵（PLAN §5.5，全部零重编码）：
  VP9/IVF → WebM（多音轨时 MKV）   H.264 → MP4(+faststart)
  MPEG-1  → MKV                    音频 → FLAC（默认）/ WAV / AAC / raw 旁路

音轨策略：--audio all（四轨全出，带 language 标签）| 单语言 | none。
纪律：
  * 帧数对账失败 = fail（错钥/截断的强信号），绝不静默导出；
  * 缺 audio key 跳过该轨并报告（绝不产噪音轨）；
  * .part 原子写，失败产物改名 .bad 留证；
  * 成功判据 = ffmpeg 全量零错误（verify.py），头部魔数探测只作警告。
"""

from __future__ import annotations

import json
import os
import struct
import tempfile
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import crypto, usm, verify
from . import games as gmod
from .audio import adx as adx_mod
from .audio import hca as hca_mod
from .audio import pcm
from .audio.pcm import FfmpegError

VIDEO_FMT_FLAG = {"vp9": "ivf", "h264": "h264", "mpeg1": "mpeg1video"}
#: 输出 muxer 名称（.part 临时后缀无法靠扩展名推断，必须显式指定）
MUX_NAME = {"webm": "webm", "mp4": "mp4", "mkv": "matroska"}
CONTAINER_EXT = {"webm": ".webm", "mp4": ".mp4", "mkv": ".mkv"}

AUDIO_ALL = "all"
AUDIO_NONE = "none"


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class Options:
    audio: str = AUDIO_ALL          # all | none | zho/eng/jpn/kor
    audio_format: str = "flac"      # flac | wav | aac | raw（raw = 原始码流旁路，容器内无音轨）
    container: str = "auto"         # auto | mkv | webm | mp4
    verify: bool = True
    jobs: int = 1


@dataclass
class Target:
    game_id: str
    rel_video: str                  # 视频相对路径（含 .usm）—— 决定输出子目录
    path: Path
    source: str
    entry_method: str | None        # None = 密钥库未命中
    entry_key_hex: str | None
    entry_audio_hex: str | None
    via: str | None = None
    cls: str | None = None          # new / modified
    size: int = 0
    flat_stem: str | None = None    # 平铺输出文件名（run_batch 内做同名去重）


@dataclass
class Result:
    rel_video: str
    status: str                     # ok / skip / fail / cancelled
    method: str = ""
    msg: str = ""
    output: str | None = None
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 目标选择
# ---------------------------------------------------------------------------

def select_targets(profile: gmod.GameProfile, root: Path, store,
                   *, version: str | None = None, mode: str = "all",
                   pattern: str | None = None, limit: int | None = None,
                   files: dict | None = None) -> list[Target]:
    """按版本/模式/过滤选出导出目标并解析密钥。files 可传入已缓存的 gmod.scan 结果。"""
    from fnmatch import fnmatch

    if files is None:
        files = gmod.scan(root, profile)
    ordered = sorted(files.values(), key=lambda f: f.rel_video)

    if mode in ("all", "everything"):
        picked = [(f, None) for f in ordered]
    else:
        hist = store.history
        if hist is None:
            raise ValueError("该游戏没有版本历史库，无法使用版本筛选模式")
        ver = version or hist.latest_version()
        if not ver:
            raise ValueError("历史库为空，无法推断目标版本；请显式指定 --version")
        version = ver
        want = {"new", "modified"} if mode == "changed" else {mode}
        picked = []
        for f in ordered:
            entry = hist.get(store.history_candidates(f.rel_root))
            if entry is None:
                continue
            cls = hist.classify(entry, version)
            if cls in want:
                picked.append((f, cls))

    if mode == "everything":  # 追加仅存在于历史、磁盘上已没有的文件（标记为不可导出）
        seen = {f.rel_video for f, _ in picked}
        if store.history:
            for key in sorted(store.history.entries):
                name = Path(key).name
                if name.endswith(".usm") and name not in {Path(p).name for p in seen}:
                    pass  # 仅历史条目在报告层提示，不参与导出
    if pattern:
        pat = pattern.lower()
        picked = [(f, c) for f, c in picked
                  if fnmatch(f.rel_video.lower(), pat) or fnmatch(f.name.lower(), pat)]
    if limit:
        picked = picked[:limit]

    targets: list[Target] = []
    for f, cls in picked:
        hit = store.lookup(f.rel_root, target_version=version)
        e = hit.entry
        targets.append(Target(
            game_id=profile.id,
            rel_video=f.rel_video,
            path=f.path,
            source=f.source,
            entry_method=e.method if e else None,
            entry_key_hex=e.key_hex if e else None,
            entry_audio_hex=e.audio_hex if e else None,
            via=hit.via,
            cls=cls,
            size=f.size,
        ))
    return targets


# ---------------------------------------------------------------------------
# 封装矩阵
# ---------------------------------------------------------------------------

def resolve_mux(kind: str, audio_count: int, audio_format: str,
                requested: str) -> tuple[str, str, list[str]]:
    """(视频种类, 音轨数, 音频编码, 请求容器) → (容器, 生效音频编码, 纠正说明)。"""
    notes: list[str] = []
    fmt = audio_format
    in_container = audio_count > 0 and fmt != "raw"

    if requested == "auto":
        if kind == "h264":
            container = "mp4"
        elif kind == "mpeg1":
            container = "mkv"
        else:  # vp9 / unknown
            if kind == "vp9" and not in_container:
                container = "webm"
            else:
                container = "mkv"
                if kind == "vp9":
                    notes.append("带音轨导出时 WebM 不支持 FLAC/WAV，改用 MKV")
    else:
        container = requested

    if container == "webm":
        if kind not in ("vp9",):
            notes.append(f"WebM 仅支持 VP9/AV1 视频，{kind} 已改用 MKV")
            container = "mkv"
        elif in_container:
            notes.append("WebM 音频仅支持 Opus/Vorbis，带音轨导出改用 MKV")
            container = "mkv"
    if container == "mp4":
        if kind == "mpeg1":
            notes.append("MP4 不支持 MPEG-1，已改用 MKV")
            container = "mkv"
        if in_container and fmt == "wav":
            notes.append("MP4 容器下裸 PCM 兼容性差，已改用 AAC（要无损请用 flac）")
            fmt = "aac"
    if container == "mkv" and kind == "unknown":
        notes.append("视频格式未知，按 MKV 尝试")
    return container, fmt, notes


# ---------------------------------------------------------------------------
# 音频解码
# ---------------------------------------------------------------------------

def _resolve_audio_keycode(entry_method: str | None, key_hex: str | None,
                           audio_hex: str | None) -> tuple[int, str]:
    """→ (keycode, 说明)。aes 条目缺 audio key 时 keycode 置 -1 表示跳过该轨。"""
    if entry_method == "mask":
        return int(key_hex, 16), "keycode=finalKey(低56位)"
    if entry_method == "aes":
        if audio_hex:
            return int(audio_hex, 16), "keycode=audioKey"
        return -1, "缺 audio key"
    return 0, "未加密"


def _decode_one_stream(s: usm.AudioStream, method: str | None, keycode: int,
                       audio_mask: bytes | None, td: Path, ffmpeg: str,
                       idx: int, game_id: str) -> tuple[Path | None, str]:
    """单条音频流 → WAV 临时文件。返回 (路径 | None, 说明)。"""
    notes: list[str] = []
    lang_note = f"a{s.chno}"

    if s.codec == "unknown":
        return None, f"{lang_note} 未知编码，跳过"

    if s.codec == "HCA":
        raw = b"".join(s.chunks)
        # 自适应：GI 实测 HCA 音频无 USM 层掩码（cipher type 0），直接解；
        # 若 checksum 失败再试掩码流（个别代际若存在 USM 掩码式 HCA 则第二发命中）。
        candidates = [("原始", raw)]
        if method == "mask" and audio_mask is not None:
            masked = b"".join(crypto.decrypt_audio_chunk(c, audio_mask) for c in s.chunks)
            candidates.append(("掩码", masked))
        wav = None
        for label, stream in candidates:
            try:
                wav = hca_mod.decode_to_wav(stream, keycode)
                if label == "掩码":
                    notes.append("USM 层音频掩码已解（原始流 checksum 不符）")
                break
            except Exception:
                continue
        if wav is None:
            return None, f"{lang_note} HCA 解码失败（原始/掩码流均 checksum 不符）"
        frames, ch, rate = pcm.wav_frames(wav)
        meta = hca_mod.read_meta(stream)
        if meta is not None:
            raw_expect = meta.frame_count * hca_mod.SAMPLES_PER_FRAME
            trimmed_expect = raw_expect - meta.encoder_delay - meta.encoder_padding
            if frames == raw_expect and meta.encoder_delay + meta.encoder_padding > 0:
                pcm_data = pcm.trim_pcm_frames(pcm.wav_pcm(wav), ch,
                                               meta.encoder_delay, meta.encoder_padding)
                wav = pcm.make_wav_bytes(pcm_data, ch, rate)
                notes.append(f"已裁 priming（delay={meta.encoder_delay} padding={meta.encoder_padding}）")
            elif frames != trimmed_expect and frames != raw_expect:
                notes.append(f"样本数对账偏差: 实际 {frames}，预期 {trimmed_expect}（未裁）/ {raw_expect}（已裁）")
        wav_path = td / f"audio{idx}.wav"
        pcm.write_wav(wav_path, wav)
        return wav_path, "; ".join(notes) if notes else ""

    # ADX
    raw = b"".join(s.chunks)
    stream = raw
    if method == "mask" and audio_mask is not None and adx_mod.looks_encrypted(raw):
        stream = b"".join(crypto.decrypt_audio_chunk(c, audio_mask) for c in s.chunks)
        notes.append("已解 USM 层音频掩码（同步字判定为加密）")
    elif method == "mask":
        notes.append("同步字判定为明文，跳过音频掩码")
    stream, patched = adx_mod.patch_cri(stream)
    if patched:
        notes.append("(c)CRI 版权串已补")
    adx_path = td / f"audio{idx}.adx"
    adx_path.write_bytes(stream)
    wav_path = td / f"audio{idx}.wav"
    try:
        pcm.decode_adx(ffmpeg, adx_path, wav_path)
    except FfmpegError as exc:
        return None, f"{lang_note} ADX 解码失败: {exc}"
    return wav_path, "; ".join(notes) if notes else ""


# ---------------------------------------------------------------------------
# 单文件导出
# ---------------------------------------------------------------------------

def export_one(target: Target, opts: Options, out_dir: Path, ffmpeg: str) -> Result:
    t0 = time.time()
    notes: list[str] = []
    method = target.entry_method

    def _res(status: str, msg: str, output: Path | None = None) -> Result:
        return Result(target.rel_video, status, method or "", msg,
                      str(output) if output else None, time.time() - t0, notes)

    profile = gmod.GAMES[target.game_id]

    try:
        data = target.path.read_bytes()
    except OSError as exc:
        return _res("fail", f"读取失败: {exc}")

    res = usm.parse_blocks(data)
    if res.truncated:
        return _res("fail", f"文件截断/损坏: {res.error}")

    vbs = usm.video_blocks(res.blocks)
    if not vbs:
        return _res("skip", "无视频流")

    # ---- 视频基本流 ----
    if method is None:
        # 密钥库未命中 → 仅做明文探测：按明文拼接后全量解码，
        # 通过 = 真明文（放行导出）；不通过 = 缺密钥。不做任何其他动作。
        es = usm.concat_video(vbs)
        if _video_kind(es) == "unknown":
            return _res("skip", "缺密钥")
        with tempfile.TemporaryDirectory() as td_probe:
            probe = Path(td_probe) / "probe.bin"
            probe.write_bytes(es)
            ok_probe, _ = verify.ffmpeg_full_decode_ok(ffmpeg, probe, timeout=300)
        if not ok_probe:
            return _res("skip", "缺密钥")
        method = "plain(探测)"
    elif method == "plain":
        es = usm.concat_video(vbs)
    elif method == "mask":
        es = crypto.decrypt_video_mask(vbs, int(target.entry_key_hex, 16))
    elif method == "aes":
        nonce = usm.read_nonce(data)
        if nonce is None:
            return _res("skip", "aes 条目但文件内无 VIDEO_HDRINFO nonce")
        es = crypto.decrypt_video_aes(vbs, bytes.fromhex(target.entry_key_hex), nonce)
    else:
        return _res("fail", f"未知加密形态 {method}")

    # ---- 帧数对账（硬校验） ----
    ivf = usm.ivf_info(es)
    if ivf and ivf.frame_count != len(vbs):
        return _res("fail", f"帧数对账失败: 声明 {ivf.frame_count} ≠ 实际 {len(vbs)}（错钥/截断的强信号）")

    kind = _video_kind(es)
    if kind == "unknown":
        return _res("fail", "解密产物无法识别视频格式（错钥或非视频流）")

    # ---- 输出路径（平铺：config\export\文件名；同名冲突已在 run_batch 中消歧） ----
    stem = target.flat_stem or Path(target.rel_video).stem

    with tempfile.TemporaryDirectory(prefix="hoyo-usm-") as td_str:
        td = Path(td_str)
        video_tmp = td / "video.bin"
        video_tmp.write_bytes(es)

        # ---- 音轨 ----
        audio_inputs: list[Path] = []
        langs: list[str] = []
        sidecars: list[Path] = []
        dropped = 0
        if opts.audio != AUDIO_NONE and profile.has_audio:
            streams = usm.audio_streams(res.blocks)
            selected = _select_audio(streams, opts.audio, profile, notes)
            audio_mask = None
            if method == "mask" and target.entry_key_hex:
                audio_mask = crypto.build_audio_mask(crypto.build_masks(int(target.entry_key_hex, 16))[0])
            for i, s in enumerate(selected):
                keycode, key_note = _resolve_audio_keycode(
                    target.entry_method, target.entry_key_hex, target.entry_audio_hex)
                if keycode < 0:
                    notes.append(f"a{s.chno} {key_note}，跳过该轨")
                    dropped += 1
                    continue
                if opts.audio_format == "raw":
                    sidecar = _write_sidecar(out_dir, stem, s, method, audio_mask, key_note, notes, keycode)
                    if sidecar:
                        sidecars.append(sidecar)
                    continue
                wav, note = _decode_one_stream(s, target.entry_method, keycode, audio_mask,
                                               td, ffmpeg, i, profile.id)
                if note:
                    notes.append(f"a{s.chno}: {note}")
                if wav is not None:
                    audio_inputs.append(wav)
                    langs.append((profile.audio_langs or {}).get(s.chno, "und"))
                else:
                    dropped += 1
            if dropped and selected:
                notes.append(f"{dropped}/{len(selected)} 条音轨未能解码，产物只含其余音轨")
        elif opts.audio != AUDIO_NONE and not profile.has_audio:
            notes.append(f"{profile.title} USM 无音轨，按纯视频导出")

        # ---- 容器决策 ----
        container, eff_fmt, mux_notes = resolve_mux(kind, len(audio_inputs), opts.audio_format,
                                                    opts.container)
        notes.extend(mux_notes)
        out_path = out_dir / (stem + CONTAINER_EXT[container])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        part = out_path.with_suffix(out_path.suffix + ".part")

        # ---- 封装（视频永远 codec copy） ----
        try:
            _mux_video(ffmpeg, video_tmp, kind, audio_inputs, langs, container,
                       eff_fmt if len(audio_inputs) else None, part)
        except FfmpegError as exc:
            return _res("fail", f"封装失败: {exc}")

        # ---- 验收 ----
        if opts.verify:
            ok, err = verify.ffmpeg_full_decode_ok(ffmpeg, part,
                                                   ignore_dts_quirk=(kind == "mpeg1"))
            if not ok:
                bad = out_path.with_suffix(out_path.suffix + ".bad")
                os.replace(part, bad)
                return _res("fail", f"验收未通过（产物已改名 .bad）: {err}", bad)

        os.replace(part, out_path)
        for sc in sidecars:
            notes.append(f"旁路码流: {sc.name}")
        return _res("ok", "", out_path)


def _video_kind(es: bytes) -> str:
    """视频基本流类型。

    MPEG-1 必须在 H.264 之前判：两者共用 00 00 01 起始码前缀，
    MPEG-1 序列头为 00 00 01 B3，而 H.264 流首 NAL 只会是
    SPS(7)/AUD(9)/SEI(6)，绝不可能是 B3（NAL type 3 不会出现在流首）。
    """
    if usm.ivf_info(es[:64]):
        return "vp9"
    if usm.looks_like_mpeg1(es[:16]):
        return "mpeg1"
    if usm.looks_like_h264(es[:16]):
        return "h264"
    return "unknown"


def _select_audio(streams: list[usm.AudioStream], audio: str,
                  profile: gmod.GameProfile, notes: list[str]) -> list[usm.AudioStream]:
    if audio == AUDIO_ALL:
        return streams
    inv = {v: k for k, v in (profile.audio_langs or {}).items()}
    chno = inv.get(audio)
    if chno is None:
        notes.append(f"未知语言 {audio}，忽略音轨")
        return []
    for s in streams:
        if s.chno == chno:
            return [s]
    notes.append(f"文件内无 {audio}（chno{chno}）音轨")
    return []


def _write_sidecar(out_dir: Path, stem: str, s: usm.AudioStream, method: str | None,
                   audio_mask: bytes | None, key_note: str,
                   notes: list[str], keycode: int) -> Path | None:
    """--audio-format raw：解密后的原始音频码流旁路保存（完全保留原始字节）。

    HCA 按实测无 USM 层掩码，保存原始流；ADX 按同步字判定决定是否解掩码，
    并补 (c)CRI。
    """
    stream = b"".join(s.chunks)
    if s.codec == "ADX":
        if method == "mask" and audio_mask is not None and adx_mod.looks_encrypted(stream):
            stream = b"".join(crypto.decrypt_audio_chunk(c, audio_mask) for c in s.chunks)
        stream = adx_mod.patch_cri(stream)[0]
    ext = ".hca" if s.codec == "HCA" else ".adx"
    out = out_dir / f"{stem}.a{s.chno}{ext}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(stream)
    notes.append(f"a{s.chno} 旁路保存原始码流（{key_note}）")
    return out


def _mux_video(ffmpeg: str, video_tmp: Path, kind: str, audio_inputs: list[Path],
               langs: list[str], container: str, audio_codec: str | None,
               out_part: Path) -> None:
    args = ["-f", VIDEO_FMT_FLAG[kind], "-i", str(video_tmp)]
    if kind == "mpeg1":
        # MPEG-1 裸流缺时间戳，MKV muxer 拒收（Can't write packet with
        # unknown timestamp），必须 genpts
        args = ["-fflags", "+genpts"] + args
    for w in audio_inputs:
        args += ["-i", str(w)]
    args += ["-map", "0:v"]
    for j in range(len(audio_inputs)):
        args += ["-map", f"{j + 1}:a"]
    args += ["-c:v", "copy"]
    if audio_inputs and audio_codec:
        codec_flag = {"flac": "flac", "wav": "pcm_s16le", "aac": "aac"}[audio_codec]
        args += ["-c:a", codec_flag]
        if audio_codec == "aac":
            args += ["-b:a", "256k"]
        for j, lang in enumerate(langs):
            args += [f"-metadata:s:a:{j}", f"language={lang}"]
    if container == "mp4":
        args += ["-movflags", "+faststart"]
    args += ["-f", MUX_NAME[container], str(out_part)]
    try:
        pcm._run_ffmpeg(ffmpeg, args, hint="封装")
    except FfmpegError:
        if kind == "mpeg1":
            # mpeg1video 探测失败时退回 ffmpeg 自动探测再试一次
            retry = list(args)
            i = retry.index("-f")
            del retry[i:i + 2]
            pcm._run_ffmpeg(ffmpeg, retry, hint="封装（自动探测 MPEG-1）")
            return
        raise


# ---------------------------------------------------------------------------
# 批量与报告
# ---------------------------------------------------------------------------

def _worker(task: tuple) -> dict:
    target, opts, out_dir, ffmpeg = task
    return asdict(export_one(target, opts, out_dir, ffmpeg))


def run_batch(targets: list[Target], opts: Options, out_dir: Path, ffmpeg: str,
              *, progress=None, cancel: threading.Event | None = None,
              on_result=None) -> dict:
    """批量导出并写 _export_log.json。progress(rel_video, status) 回调可为 None；
    on_result(Result) 在每个目标结束时回调（GUI 用来展示逐文件详情）。

    jobs>1 采用有界提交：保持 ≤jobs 个在飞，完成一个补一个，
    cancel 触发后不再派发新目标（未开始的标记 cancelled）。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[Result] = []
    todo = list(targets)

    # 平铺输出名：basename；同名冲突用父目录名区分，仍冲突加序号
    from collections import Counter
    dup = {s for s, c in Counter(Path(t.rel_video).stem for t in todo).items() if c > 1}
    used: dict[str, int] = {}
    for t in todo:
        base = Path(t.rel_video).stem
        cand = base
        if base in dup:
            # 取最后两级目录拼接，提高区分度（Transfer/HollowLoading/Zero → HollowLoading__Zero）
            parts = Path(t.rel_video).parts
            chain = "__".join(parts[-3:-1]) if len(parts) >= 3 else ""
            cand = f"{base}__{chain}" if chain else base
        n = used.get(cand, 0)
        used[cand] = n + 1
        if n:
            cand = f"{cand}_{n + 1}"
        t.flat_stem = cand

    if opts.jobs > 1 and len(todo) > 1:
        from concurrent.futures import FIRST_COMPLETED, wait

        with ProcessPoolExecutor(max_workers=opts.jobs) as ex:
            pending: dict = {}
            next_idx = 0

            def submit_while_capacity() -> None:
                nonlocal next_idx
                while (next_idx < len(todo) and len(pending) < opts.jobs
                       and not (cancel is not None and cancel.is_set())):
                    t = todo[next_idx]
                    pending[ex.submit(_worker, (t, opts, out_dir, ffmpeg))] = t
                    next_idx += 1

            submit_while_capacity()
            while pending:
                done_set, _ = wait(list(pending.keys()), return_when=FIRST_COMPLETED)
                for fut in done_set:
                    t = pending.pop(fut)
                    try:
                        results.append(Result(**fut.result()))
                    except Exception as exc:            # 进程内异常兜底
                        results.append(Result(t.rel_video, "fail", msg=f"任务执行异常: {exc}"))
                    if on_result:
                        on_result(results[-1])
                    if progress:
                        progress(results[-1].rel_video, results[-1].status)
                submit_while_capacity()
            for t in todo[next_idx:]:
                results.append(Result(t.rel_video, "cancelled", "", "已取消（未开始）"))
                if on_result:
                    on_result(results[-1])
                if progress:
                    progress(t.rel_video, "cancelled")
    else:
        for t in todo:
            if cancel is not None and cancel.is_set():
                results.append(Result(t.rel_video, "cancelled", "", "用户取消"))
                if on_result:
                    on_result(results[-1])
                if progress:
                    progress(t.rel_video, "cancelled")
                continue
            r = export_one(t, opts, out_dir, ffmpeg)
            results.append(r)
            if on_result:
                on_result(r)
            if progress:
                progress(r.rel_video, r.status)

    summary = {
        "total": len(todo),
        "ok": sum(1 for r in results if r.status == "ok"),
        "skip": sum(1 for r in results if r.status == "skip"),
        "fail": sum(1 for r in results if r.status == "fail"),
        "cancelled": sum(1 for r in results if r.status == "cancelled"),
    }
    game_tag = targets[0].game_id if targets else "export"
    report = {
        "game": game_tag,
        "summary": summary,
        "results": sorted((asdict(r) for r in results), key=lambda d: d["rel_video"]),
    }
    report_path = out_dir / f"_export_log_{game_tag}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report
