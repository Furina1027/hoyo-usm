"""hoyo-usm 命令行入口：check / status / list / probe（export 自 M2 起可用）。

所有子命令只读：不写密钥库、不动游戏目录、不产生输出文件（export 除外，M2）。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
import threading
from fnmatch import fnmatch
from pathlib import Path

from . import games as gmod
from . import usm
from .identify import (direct_target as _direct_target,
                       guess_game_by_dir as _guess_game,
                       guess_game_by_keys as _guess_game_by_keys,
                       guess_game_by_md5 as _guess_game_by_md5,
                       locate_by_name as _locate_by_name)
from .keys import KeyStore

__version__ = "0.1.0"

#: 仓库内自包含密钥快照目录
DEFAULT_KEYS_DIR = Path(__file__).resolve().parent.parent / "keys"

MODE_NEW = "new"
MODE_MODIFIED = "modified"
MODE_ALL = "all"
MODE_EVERYTHING = "everything"
MODES = (MODE_NEW, MODE_MODIFIED, "changed", MODE_ALL, MODE_EVERYTHING)


def _keys_dir(args: argparse.Namespace) -> Path:
    return Path(args.keys_dir).expanduser().resolve()


def _ffmpeg_path() -> str | None:
    val = os.environ.get("HOYO_USM_FFMPEG")
    if val and Path(val).is_file():
        return val
    return shutil.which("ffmpeg")


def _dep(name: str) -> str:
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return "不可用"
    return "可用" if spec is not None else "缺"


def _human(n: int) -> str:
    x = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if x < 1024 or unit == "GiB":
            return f"{int(x)} B" if unit == "B" else f"{x:.1f} {unit}"
        x /= 1024
    return f"{x:.1f} GiB"


def _load_store(args: argparse.Namespace, prof: gmod.GameProfile) -> KeyStore:
    return KeyStore(
        _keys_dir(args),
        key_file=prof.key_file,
        history_file=prof.history_file,
        versions_file=prof.versions_file,
        by_path_file=prof.by_path_file,
        by_path_prefixes=prof.by_path_prefixes,
    )


def _game_root(args: argparse.Namespace, prof: gmod.GameProfile) -> Path | None:
    override = getattr(args, "game_root", None)
    if override:
        for spec in override:
            gid, _, p = spec.partition("=")
            if gmod.resolve_game(gid).id == prof.id:
                return Path(p) if p else None
    return gmod.resolve_root(prof)


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

def cmd_check(args: argparse.Namespace) -> int:
    keys_dir = _keys_dir(args)
    data: dict = {"keys_dir": str(keys_dir)}

    print(f"hoyo-usm {__version__} 自检")
    print(f"python    : {sys.version.split()[0]}  ({sys.executable})")
    ff = _ffmpeg_path()
    print(f"ffmpeg    : {ff or '未找到（M2 导出/校验需要，可用 HOYO_USM_FFMPEG 指定）'}")
    deps = {
        "numpy": _dep("numpy"),
        "pycryptodome": _dep("Crypto"),
        "cricodecs": _dep("cricodecs"),
    }
    print("依赖      : " + "  ".join(f"{k}={v}" for k, v in deps.items()))
    data["ffmpeg"] = ff
    data["deps"] = deps

    print(f"密钥库    : {keys_dir}" + ("（存在）" if keys_dir.is_dir() else "（不存在！）"))
    games_out = {}
    for gid, prof in gmod.GAMES.items():
        try:
            store = _load_store(args, prof)
            st = store.stats
            hist = store.history
            games_out[gid] = {
                "codename": prof.codename,
                "keys": st.as_dict(),
                "by_path": len(store.by_path),
                "versions": len(store.versions),
                "history": len(hist.entries) if hist else None,
            }
            print(f"  {gid:<4}({prof.codename}) keys={st.total:<5}"
                  f"(mask {st.mask} / aes {st.aes} / plain {st.plain} / 丢弃 {st.dropped}"
                  f" / aes带audio {st.aes_with_audio})"
                  f" by_path={len(store.by_path)} versions={len(store.versions)}"
                  f" history={len(hist.entries) if hist else '-'}")
        except Exception as exc:  # 密钥库损坏时报告而不是崩溃
            games_out[gid] = {"error": str(exc)}
            print(f"  {gid:<4}密钥库加载失败：{exc}")
    data["games"] = games_out

    print("游戏目录  :")
    roots_out = {}
    for gid, prof in gmod.GAMES.items():
        root = _game_root(args, prof)
        roots_out[gid] = str(root) if root else None
        if root:
            n = sum(1 for _ in root.rglob("*.usm"))
            print(f"  {gid:<4}✓ {root}  （*.usm：{n}）")
        else:
            print(f"  {gid:<4}未找到（可用 --game-root {gid}=路径 或环境变量指定）")
    data["game_roots"] = roots_out

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    if not keys_dir.is_dir():
        print("错误：密钥库目录不存在", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def cmd_status(args: argparse.Namespace) -> int:
    prof = gmod.resolve_game(args.game)
    root = _game_root(args, prof)
    if root is None:
        print(f"错误：未找到 {prof.title} 游戏目录，请用 --game-root {prof.id}=路径 指定", file=sys.stderr)
        return 2
    store = _load_store(args, prof)
    files = gmod.scan(root, prof)

    c = {"mask": 0, "aes": 0, "aes_no_audio": 0, "plain": 0, "missing": 0}
    missing: list[str] = []
    for f in files.values():
        hit = store.lookup(f.rel_root)
        e = hit.entry
        if e is None:
            c["missing"] += 1
            if len(missing) < 15:
                missing.append(f.rel_video)
        elif e.method == "mask":
            c["mask"] += 1
        elif e.method == "plain":
            c["plain"] += 1
        else:
            c["aes"] += 1
            if not e.audio_hex and prof.has_audio:
                c["aes_no_audio"] += 1

    total = len(files)
    print(f"{prof.title}（{prof.codename}）本地 USM 密钥覆盖率")
    print(f"  游戏目录 : {root}")
    print(f"  文件总数 : {total}（基线 {sum(1 for f in files.values() if f.source == 'baseline')}"
          f" / 热更 {sum(1 for f in files.values() if f.source == 'hotfix')}）")
    print(f"  mask     : {c['mask']}")
    print(f"  aes      : {c['aes']}" + (f"（其中 {c['aes_no_audio']} 个缺 audio key，音轨将跳过）" if c["aes_no_audio"] else ""))
    print(f"  plain    : {c['plain']}")
    print(f"  缺密钥   : {c['missing']}")
    if missing:
        print("  缺失示例 :")
        for m in missing:
            print(f"    - {m}")
    covered = c["mask"] + c["aes"] + c["plain"]
    pct = covered / total * 100 if total else 100.0
    print(f"  覆盖率   : {covered}/{total}（{pct:.1f}%）")
    if args.json:
        print(json.dumps({"game": prof.id, "root": str(root), "total": total, **c,
                          "coverage_pct": round(pct, 2), "missing": missing},
                         ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def _iter_targets(args: argparse.Namespace, prof: gmod.GameProfile, root: Path,
                  store: KeyStore) -> list[tuple[gmod.ScannedFile, str | None]]:
    """按 --mode 选出目标：返回 (文件, 状态标记)。"""
    files = gmod.scan(root, prof)
    mode = args.mode

    if mode in (MODE_ALL, MODE_EVERYTHING):
        return [(f, None) for f in sorted(files.values(), key=lambda f: f.rel_video)]

    hist = store.history
    if hist is None:
        raise SystemExit("错误：该游戏没有版本历史库，无法使用 new/modified 模式")
    version = args.target_version or hist.latest_version()
    if not version:
        raise SystemExit("错误：历史库为空，无法推断最新版本；请显式指定 --version")
    args.target_version = version

    out: list[tuple[gmod.ScannedFile, str | None]] = []
    for f in sorted(files.values(), key=lambda f: f.rel_video):
        entry = hist.get(store.history_candidates(f.rel_root))
        if entry is None:
            continue
        cls = hist.classify(entry, version)
        if cls == mode:
            out.append((f, cls))
    return out


def cmd_list(args: argparse.Namespace) -> int:
    prof = gmod.resolve_game(args.game)
    root = _game_root(args, prof)
    if root is None:
        print(f"错误：未找到 {prof.title} 游戏目录，请用 --game-root {prof.id}=路径 指定", file=sys.stderr)
        return 2
    store = _load_store(args, prof)
    targets = _iter_targets(args, prof, root, store)

    pat = args.filter.lower() if args.filter else None
    rows = []
    for f, cls in targets:
        if pat and not (fnmatch(f.rel_video.lower(), pat) or fnmatch(f.name.lower(), pat)):
            continue
        hit = store.lookup(f.rel_root, target_version=args.target_version)
        rows.append((f, cls, hit))
        if args.limit and len(rows) >= args.limit:
            break

    ver = args.target_version
    print(f"{prof.title} 目标清单" + (f"（版本 {ver}，模式 {args.mode}）" if ver else f"（模式 {args.mode}）"))
    if not rows:
        print("  （无匹配目标）")
        return 0
    print(f"  {'文件':<60} {'大小':>10}  {'密钥':<28} 来源")
    for f, cls, hit in rows:
        if hit.entry is None:
            key = f"缺密钥 via={hit.via or '-'}"
        else:
            key = hit.entry.method
            if hit.entry.method == "aes":
                key += "（audio " + ("有" if hit.entry.audio_hex else "缺") + "）"
            key += f" via={hit.via}"
        state = f"[{cls}]" if cls else ""
        print(f"  {f.rel_video:<60} {_human(f.size):>10}  {key:<28} {f.source} {state}")
    print(f"  共 {len(rows)} 个" + ("（--limit 截断）" if args.limit and len(rows) >= args.limit else ""))
    return 0


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

def cmd_export(args: argparse.Namespace) -> int:
    from . import export as export_mod

    prof = gmod.resolve_game(args.game) if args.game else None
    given_paths = [Path(f).expanduser() for f in (args.files or [])]
    file_paths = [p for p in given_paths if p.is_file()]
    all_direct = bool(given_paths) and len(file_paths) == len(given_paths)
    if prof is None:
        if file_paths:
            prof = (_guess_game_by_keys(file_paths, _keys_dir(args))
                    or _guess_game_by_md5(file_paths, _keys_dir(args)))
            if prof is None:
                print("错误：无法按文件名/内容 md5 识别游戏（不在密钥库与历史库中），请加 --game gi|hsr|zzz",
                      file=sys.stderr)
                return 2
        else:
            print("错误：需要 --game gi|hsr|zzz（或直接给出 .usm 文件路径）", file=sys.stderr)
            return 2
    root = _game_root(args, prof)
    if not all_direct and root is None:
        print(f"错误：未找到 {prof.title} 游戏目录（按版本/通配/裸名选择时需要），"
              f"请用 --game-root {prof.id}=路径 指定", file=sys.stderr)
        return 2
    if args.audio not in ("all", "none") and prof.audio_langs is None:
        print(f"错误：{prof.title} USM 无音轨，--audio 只能取 none", file=sys.stderr)
        return 2
    if args.audio not in ("all", "none") and args.audio not in prof.audio_langs.values():
        print(f"错误：未知语言 {args.audio}，可选：{'/'.join(sorted(set(prof.audio_langs.values())))}", file=sys.stderr)
        return 2
    ffmpeg = _ffmpeg_path()
    if ffmpeg is None:
        print("错误：未找到 ffmpeg（可用 HOYO_USM_FFMPEG 指定路径）", file=sys.stderr)
        return 2

    store = _load_store(args, prof)
    if args.files:
        # 位置参数就是全部目标：完整路径直接导出；裸名/通配按模式匹配
        targets = []
        for f in args.files:
            p = Path(f).expanduser()
            if p.is_file():
                targets.append(_direct_target(prof, root, store, p, args.target_version))
            else:
                pat = f if ("*" in f or "?" in f) else f"*{p.stem}*"
                try:
                    targets.extend(
                        export_mod.select_targets(prof, root, store, version=args.target_version,
                                                  mode=MODE_ALL, pattern=pat))
                except ValueError as exc:
                    print(f"错误：{exc}", file=sys.stderr)
                    return 2
        seen: set = set()
        uniq = []
        for t in targets:
            if t.rel_video not in seen:
                seen.add(t.rel_video)
                uniq.append(t)
        targets = uniq
    else:
        try:
            targets = export_mod.select_targets(prof, root, store, version=args.target_version,
                                                mode=args.mode, pattern=args.filter, limit=args.limit)
        except ValueError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 2

    if not targets:
        print("无匹配目标")
        return 0
    if args.files and prof.by_path_file:
        externals = [t for t in targets if t.source == "external" and t.via == "name"]
        if externals:
            print(f"  警告：{len(externals)} 个文件在游戏目录外且 md5 未能恢复原始路径，按文件名查 key —— "
                  "同名异钥文件可能取错，建议保留游戏内目录结构或在游戏目录内导出", file=sys.stderr)
    if len(targets) > 50 and not args.yes:
        print(f"目标 {len(targets)} 个（>50）。确认请加 --yes，或用 --limit/--filter 缩小范围。", file=sys.stderr)
        return 2

    ver_tag = args.target_version
    if not ver_tag:
        if args.files:
            ver_tag = "direct"
        elif store.history and args.mode in (MODE_NEW, MODE_MODIFIED):
            ver_tag = store.history.latest_version()
    out_dir = Path(args.out_dir).expanduser().resolve() / (ver_tag or args.mode)
    opts = export_mod.Options(audio=args.audio, audio_format=args.audio_format,
                              container=args.container, verify=not args.no_verify,
                              jobs=args.jobs)

    print(f"{prof.title} 导出：{len(targets)} 个目标 → {out_dir}"
          f"（audio={args.audio}/{args.audio_format}, container={args.container}"
          f", verify={'开' if opts.verify else '关'}, jobs={opts.jobs}）")

    cancel = threading.Event()
    done = [0]

    def _progress(rel: str, status: str) -> None:
        done[0] += 1
        mark = {"ok": "✓", "skip": "∅", "fail": "✗", "cancelled": "-"}.get(status, "?")
        print(f"  [{done[0]}/{len(targets)}] {mark} {status:<9} {rel}")

    try:
        report = export_mod.run_batch(targets, opts, out_dir, ffmpeg,
                                      progress=_progress, cancel=cancel)
    except KeyboardInterrupt:
        print("\n已中断（部分产物可能仍在写盘）", file=sys.stderr)
        return 130

    s = report["summary"]
    print(f"完成：ok {s['ok']} / skip {s['skip']} / fail {s['fail']}"
          + (f" / cancelled {s['cancelled']}" if s["cancelled"] else "")
          + f"，报告 {report['report_path']}")
    return 1 if s["fail"] else 0


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------

def cmd_probe(args: argparse.Namespace) -> int:
    from .probe import probe_file

    raw = Path(args.file).expanduser()
    path = raw if raw.is_file() else None
    if path is None:
        hit = _locate_by_name(raw.stem if raw.suffix == ".usm" else raw.name)
        if hit is None:
            print(f"错误：找不到文件 {raw}", file=sys.stderr)
            return 2
        path = hit[1].path

    try:
        out = probe_file(path, game=args.game, keys_dir=_keys_dir(args))
    except FileNotFoundError:
        print(f"错误：找不到文件 {raw}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    if "error" in out:
        print(f"错误：{out['error']}", file=sys.stderr)
        return 2

    ivf = out["video"]["ivf"]
    nonce = out["nonce"]
    key = out["key"]
    streams = out["audio"]
    print(f"文件   : {out['file']}  （{_human(out['size'])}）")
    print(f"游戏   : {out['game_title']}（{out['codename']}）" + ("" if args.game else "［自动识别］"))
    print(f"块     : {out['blocks']}  分布 {out['magic_hist']}"
          + (f"  截断={out['truncated']}" if out["truncated"] else ""))
    print(f"视频   : {out['video']['blocks']} 帧块 ｜ {out['video']['desc']}")
    print(f"nonce  : {nonce or '无（仅 method2 需要）'}")
    if streams:
        langs = gmod.GAMES[out["game"]].audio_langs or {}
        print("音频   : " + "  ".join(
            f"a{s['chno']}={s['codec']}×{s['blocks']}块" + (f"[{langs.get(s['chno'], '?')}]" if langs else "")
            for s in streams))
    else:
        print("音频   : 无 @SFA 数据块（纯视频）")
    if key is None:
        print(f"密钥   : 未命中 via={key or '无'}")
    else:
        audio_part = "audio=" + (key["audio"] or "缺") if key["method"] == "aes" else ""
        print(f"密钥   : {key['method']} via={key['via']} (matched={key['matched']}) {audio_part}".rstrip())
    print(f"管线   : {out['pipeline']}")
    for w in out["warnings"]:
        print(f"警告   : {w}")
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--keys-dir", default=str(DEFAULT_KEYS_DIR),
                        help=f"自包含密钥快照目录（默认 {DEFAULT_KEYS_DIR}）")
    common.add_argument("--game-root", action="append", metavar="ID=路径",
                        help="游戏根目录覆盖，可重复：--game-root gi=E:\\...")

    p = argparse.ArgumentParser(
        prog="hoyo-usm",
        description="无损解密并导出 原神/星穹铁道/绝区零 USM 过场动画（clean-room 实现，只读密钥快照）",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", parents=[common], help="环境 / 密钥库 / 游戏目录自检")
    c.add_argument("--json", action="store_true", help="附加机器可读 JSON 输出")
    c.set_defaults(func=cmd_check)

    c = sub.add_parser("status", parents=[common], help="本地文件 × 密钥覆盖率")
    c.add_argument("--game", required=True, help="gi | hsr | zzz")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_status)

    c = sub.add_parser("list", parents=[common], help="导出目标清单（版本变更 / 全量）")
    c.add_argument("--game", required=True, help="gi | hsr | zzz")
    c.add_argument("--version", dest="target_version", help="目标游戏版本（默认取历史库最新）")
    c.add_argument("--mode", default=MODE_ALL, choices=MODES,
                   help="new=版本新增 / modified=版本更新 / all=磁盘全部 / everything=all+仅历史")
    c.add_argument("--filter", help="文件名/相对路径通配（fnmatch，不区分大小写）")
    c.add_argument("--limit", type=int, help="最多列出 N 个")
    c.set_defaults(func=cmd_list)

    c = sub.add_parser("probe", parents=[common], help="只读解析：容器结构 / 加密形态 / 管线")
    c.add_argument("file", help=".usm 路径或裸文件名（裸文件名将在已配置的游戏目录中查找）")
    c.add_argument("--game", help="gi | hsr | zzz（默认按路径自动识别）")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_probe)

    c = sub.add_parser("export", parents=[common], help="无损解密并导出（视频 codec copy；音频 FLAC/WAV/AAC/raw）")
    c.add_argument("files", nargs="*",
                   help="直接指定的 .usm：完整路径或裸文件名/通配（裸名命中多个则全部导出）；"
                        "不给位置参数时按 --version/--mode/--filter 选目标。"
                        "给完整路径时可省略 --game（按文件名自动识别游戏）")
    c.add_argument("--game", help="gi | hsr | zzz（直接给文件路径时可省略，按文件名自动识别）")
    c.add_argument("--version", dest="target_version", help="目标游戏版本（默认取历史库最新）")
    c.add_argument("--mode", default=MODE_ALL, choices=MODES,
                   help="目标选择模式：new=该版本首次加入 / modified=该版本更新 / changed=两者 / all（默认 all）")
    c.add_argument("--filter", help="文件名/相对路径通配（fnmatch，不区分大小写）")
    c.add_argument("--limit", type=int, help="最多导出 N 个")
    c.add_argument("--audio", default="all", help="音轨：all=四轨全出 / zho|eng|jpn|kor=单轨 / none（默认 all）")
    c.add_argument("--audio-format", default="flac", choices=("flac", "wav", "aac", "raw"),
                   help="音频输出：flac/wav=无损，aac=兼容档，raw=解密后原始码流旁路（默认 flac）")
    c.add_argument("--container", default="auto", choices=("auto", "mkv", "webm", "mp4"),
                   help="输出容器（默认 auto：VP9→WebM、H264→MP4、MPEG1/多音轨→MKV）")
    c.add_argument("--no-verify", action="store_true", help="跳过 ffmpeg 全量零错误验收（不建议）")
    c.add_argument("--jobs", type=int, default=1, help="并行进程数（默认 1；>1 时不支持 Ctrl+C 优雅取消）")
    c.add_argument("--yes", action="store_true", help="目标 >50 个时跳过确认")
    c.add_argument("-o", "--out-dir", default=str(DEFAULT_KEYS_DIR.parent / "export"),
                   help="输出根目录（默认 <仓库>/export，实际写入 <out>/<版本>/）")
    c.set_defaults(func=cmd_export)

    c = sub.add_parser("gui", help="启动图形界面（本地 Web 服务 + 原生窗口，需 pip install hoyo-usm[gui]）")
    c.add_argument("--browser", action="store_true", help="用系统浏览器打开（回退模式）")
    c.add_argument("--port", type=int, default=8788, help="服务端口（默认 8788，被占用自动顺延）")
    c.add_argument("--no-open", action="store_true", help="仅启动服务，不自动打开窗口/浏览器")
    c.set_defaults(func=cmd_gui)

    return p


def cmd_gui(args: argparse.Namespace) -> int:
    from .config import Settings
    from .gui.app import launch_gui

    settings = Settings.load()
    if getattr(args, "keys_dir", None):
        settings.keys_dir = str(Path(args.keys_dir).expanduser().resolve())
    return launch_gui(settings, browser=args.browser, port=args.port,
                      open_browser=not args.no_open)


def main(argv: list[str] | None = None) -> int:
    # Windows 下输出经管道/重定向时默认跟随 ANSI 代码页（GBK），统一为 UTF-8
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower() not in ("utf-8", "utf8"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
