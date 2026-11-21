"""FastAPI 应用：GUI 后端（仅绑定 127.0.0.1）。

复用 hoyo_usm 核心模块（games/keys/export/probe），任务在 gui.tasks.TaskManager
后台线程执行；除用户手动触发的密钥更新外零网络请求。

性能：KeyStore（密钥库 JSON）与游戏目录扫描结果按 (目录, mtime) 缓存，
设置变更 / 密钥更新 / 手动刷新时失效。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .. import detect as detect_mod
from .. import games as gmod
from .. import identify
from ..config import Settings, app_data_dir, bundled_keys_dir, effective_keys_dir, user_keys_dir
from ..keys import History, KeyStore
from ..probe import probe_file
from .tasks import TaskManager

#: 密钥更新涉及的 8 个数据文件
KEY_FILES = ["hk4e_keys.json", "hk4e_history.json",
             "hkrpg_keys.json", "hkrpg_history.json", "hkrpg_keys_versions.json",
             "nap_keys.json", "nap_history.json", "nap_keys_by_path.json"]


def _ffmpeg(settings: Settings) -> str | None:
    if settings.ffmpeg_path and Path(settings.ffmpeg_path).is_file():
        return settings.ffmpeg_path
    from ..config import bundled_ffmpeg
    bundled = bundled_ffmpeg()
    if bundled:
        return str(bundled)
    return shutil.which("ffmpeg") or os.environ.get("HOYO_USM_FFMPEG")


def _keys_dir(settings: Settings) -> Path:
    return effective_keys_dir(settings)


def _game_root(settings: Settings, prof: gmod.GameProfile) -> Path | None:
    return gmod.resolve_root(prof, config_roots=settings.game_roots)


class _Cache:
    """KeyStore 与目录扫描缓存（线程安全）。"""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.stores: dict[tuple, KeyStore] = {}
        self.scans: dict[tuple, dict] = {}

    def clear(self) -> None:
        with self.lock:
            self.stores.clear()
            self.scans.clear()

    def store(self, settings: Settings, prof: gmod.GameProfile) -> KeyStore:
        kd = _keys_dir(settings)
        try:
            mt = (kd / prof.key_file).stat().st_mtime
        except OSError:
            mt = 0
        k = (prof.id, str(kd), mt)
        with self.lock:
            s = self.stores.get(k)
        if s is None:
            s = KeyStore(kd, key_file=prof.key_file, history_file=prof.history_file,
                         versions_file=prof.versions_file, by_path_file=prof.by_path_file,
                         by_path_prefixes=prof.by_path_prefixes)
            with self.lock:
                self.stores = {kk: v for kk, v in self.stores.items() if kk[0] != prof.id}
                self.stores[k] = s
        return s

    def scan(self, prof: gmod.GameProfile, root: Path) -> dict:
        k = (prof.id, str(root))
        with self.lock:
            hit = self.scans.get(k)
        if hit is None:
            hit = gmod.scan(root, prof)
            with self.lock:
                self.scans[k] = hit
        return hit


_cache = _Cache()


def _store(settings: Settings, prof: gmod.GameProfile) -> KeyStore:
    return _cache.store(settings, prof)


def _version_list(store: KeyStore) -> list[str]:
    if store.history is None:
        return []
    return sorted({str(v.get("version")) for e in store.history.entries.values()
                   for v in e.versions if v.get("version")},
                  key=History._version_key, reverse=True)


def _env_report(settings: Settings) -> dict:
    from ..export import select_targets

    deps = {}
    for name, mod in (("numpy", "numpy"), ("pycryptodome", "Crypto"), ("cricodecs", "cricodecs")):
        try:
            __import__(mod)
            deps[name] = True
        except ImportError:
            deps[name] = False
    detect_mod.start_background_scan()
    detected = detect_mod.cached_game_roots().get("result") or {}
    games_out = {}
    for gid, prof in gmod.GAMES.items():
        info: dict = {"title": prof.title, "codename": prof.codename,
                      "has_audio": prof.has_audio}
        store = None
        try:
            store = _store(settings, prof)
            info["keys"] = store.stats.as_dict()
            info["by_path"] = len(store.by_path)
            info["history"] = len(store.history.entries) if store.history else None
            vs = _version_list(store)
            info["latest_version"] = vs[0] if vs else None
        except Exception as exc:
            info["error"] = str(exc)
        root = _game_root(settings, prof)
        info["root"] = str(root) if root else None
        info["root_found"] = root is not None
        info["detected"] = detected.get(gid)
        if root and store is not None:
            files = _cache.scan(prof, root)
            targets = select_targets(prof, root, store, files=files)
            by_m: dict[str, int] = {"mask": 0, "aes": 0, "plain": 0, "missing": 0}
            for t in targets:
                by_m[t.entry_method or "missing"] = by_m.get(t.entry_method or "missing", 0) + 1
            info["usm_count"] = len(targets)
            info["usm_bytes"] = sum(t.size for t in targets)
            info["local"] = by_m
            info["covered"] = len(targets) - by_m["missing"]
            if info.get("latest_version"):
                try:
                    info["latest_new"] = len(select_targets(
                        prof, root, store, version=info["latest_version"], mode="new",
                        files=files))
                except ValueError:
                    info["latest_new"] = None
        games_out[gid] = info
    return {"ffmpeg": _ffmpeg(settings), "deps": deps, "games": games_out,
            "keys_dir": str(_keys_dir(settings)),
            "keys_source": _keys_source(settings),
            "out_dir": str(_default_out(settings))}


def _keys_source(settings: Settings) -> str:
    if settings.keys_dir:
        return "custom"
    return "user" if _keys_dir(settings) != bundled_keys_dir() else "bundled"


def _default_out(settings: Settings) -> Path:
    if settings.out_dir:
        return Path(settings.out_dir)
    if getattr(sys, "frozen", False):
        return app_data_dir() / "export"       # 便携版：exe旁 config/export；安装版：APPDATA
    return Path(__file__).resolve().parent.parent.parent / "export"


class SettingsBody(BaseModel):
    keys_dir: str | None = None
    game_roots: dict[str, str] | None = None
    ffmpeg_path: str | None = None
    out_dir: str | None = None
    jobs: int | None = None
    theme: str | None = None
    wizard_done: bool | None = None
    key_update_url: str | None = None
    audio: str | None = None
    audio_format: str | None = None
    container: str | None = None
    verify: bool | None = None


class IdentifyBody(BaseModel):
    paths: list[str]


class ExportBody(BaseModel):
    game: str | None = None
    paths: list[str] | None = None
    mode: str | None = None
    version: str | None = None
    filter: str | None = None
    limit: int | None = None
    audio: str = "all"
    audio_format: str = "flac"
    container: str = "auto"
    verify: bool = True
    jobs: int = 1
    out_dir: str | None = None


class OpenBody(BaseModel):
    path: str
    select: bool = False


class PathsBody(BaseModel):
    paths: list[str]


class ScanDirBody(BaseModel):
    dir: str


class KeysUpdateBody(BaseModel):
    url: str | None = None


class CheckPathBody(BaseModel):
    path: str
    kind: str = "dir"           # dir / file / game:<gid>


def _expand_usm(raw_paths: list[str]) -> list[str]:
    """文件 / 目录混合输入 → 去重的 .usm 文件列表（目录递归）。"""
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_paths:
        p = Path(raw).expanduser()
        cands = sorted(p.rglob("*.usm")) if p.is_dir() else [p]
        for c in cands:
            if c.is_file() and c.suffix.lower() == ".usm":
                s = str(c.resolve())
                if s not in seen:
                    seen.add(s)
                    out.append(s)
    return out


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="hoyo-usm gui", docs_url=None, redoc_url=None)
    manager = TaskManager(history_path=app_data_dir() / "tasks.json")
    app.state.manager = manager
    app.state.settings = settings
    detect_mod.start_background_scan()   # 服务启动即后台扫描游戏目录

    # ---- 环境 ----
    @app.get("/api/env")
    def api_env(refresh: bool = False):
        if refresh:
            _cache.clear()
        return _env_report(settings)

    @app.get("/api/detect")
    def api_detect():
        detect_mod.start_background_scan()
        c = detect_mod.cached_game_roots()
        return {"result": c["result"], "done": c["done"]}

    @app.post("/api/check-path")
    def api_check_path(body: CheckPathBody):
        """路径即时校验（设置/向导输入框旁的状态提示）。"""
        p = Path(body.path.strip()).expanduser() if body.path.strip() else None
        if p is None:
            return {"ok": False, "msg": "未填写"}
        if body.kind == "file":
            return {"ok": p.is_file(), "msg": "" if p.is_file() else "文件不存在"}
        if not p.is_dir():
            return {"ok": False, "msg": "目录不存在"}
        if body.kind.startswith("game:"):
            gid = body.kind.split(":", 1)[1]
            if gid not in gmod.GAMES:
                return {"ok": False, "msg": "未知游戏"}
            prof = gmod.GAMES[gid]
            n = sum(len(list((p / d).rglob("*.usm")))
                    for d in prof.baseline_dirs + prof.hotfix_dirs if (p / d).is_dir())
            if not n:
                return {"ok": False, "msg": "目录中没有找到过场动画：请选择包含游戏主程序的文件夹"}
            return {"ok": True, "msg": f"找到 {n} 个 .usm", "count": n}
        return {"ok": True, "msg": ""}

    # ---- 设置 ----
    @app.get("/api/settings")
    def api_settings_get():
        d = dict(settings.__dict__)
        d["keys_dir_effective"] = str(_keys_dir(settings))
        d["keys_dir_bundled"] = str(bundled_keys_dir())
        d["out_dir_effective"] = str(_default_out(settings))
        d["ffmpeg_effective"] = _ffmpeg(settings)
        d["app_data_dir"] = str(app_data_dir())
        return d

    @app.put("/api/settings")
    def api_settings_put(body: SettingsBody):
        patch = body.model_dump(exclude_none=True)
        for k, v in patch.items():
            setattr(settings, k, v)
        settings.save()
        if {"keys_dir", "game_roots"} & patch.keys():
            _cache.clear()
        return {"ok": True, "settings": dict(settings.__dict__)}

    # ---- 版本/文件 ----
    @app.get("/api/versions")
    def api_versions(game: str):
        prof = gmod.resolve_game(game)
        vs = _version_list(_store(settings, prof))
        return {"versions": vs, "latest": vs[0] if vs else None}

    @app.get("/api/files")
    def api_files(game: str, mode: str = "all", version: str | None = None,
                  filter: str | None = None, limit: int | None = None, refresh: bool = False):
        from ..export import select_targets
        prof = gmod.resolve_game(game)
        root = _game_root(settings, prof)
        if root is None:
            raise HTTPException(400, f"未找到 {prof.title} 游戏目录：请在设置中选择")
        if refresh:
            _cache.clear()
        store = _store(settings, prof)
        try:
            targets = select_targets(prof, root, store, version=version, mode=mode,
                                     pattern=filter, limit=limit,
                                     files=_cache.scan(prof, root))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        # 每个文件的首次加入版本（列表展示用）
        first_ver: dict[str, str | None] = {}
        hist = store.history
        if hist is not None:
            files = _cache.scan(prof, root)
            for t in targets:
                f = files.get(t.rel_video)
                e = hist.get(store.history_candidates(f.rel_root)) if f else None
                first_ver[t.rel_video] = str(e.versions[0].get("version")) if e and e.versions else None
        return {"game": prof.id, "title": prof.title, "has_audio": prof.has_audio,
                "langs": prof.audio_langs, "versions": _version_list(store),
                "root": str(root),
                "targets": [t.__dict__ | {"path": str(t.path),
                                          "version": first_ver.get(t.rel_video)}
                            for t in targets]}

    # ---- probe ----
    @app.get("/api/probe")
    def api_probe(path: str, game: str | None = None):
        try:
            return probe_file(Path(path), game=game, keys_dir=_keys_dir(settings),
                              config_roots=settings.game_roots)
        except FileNotFoundError:
            raise HTTPException(404, "文件不存在")
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    # ---- 外部文件识别 ----
    @app.post("/api/expand")
    def api_expand(body: PathsBody):
        """拖入/选择的文件与目录 → .usm 文件列表。"""
        return {"files": _expand_usm(body.paths)}

    @app.post("/api/identify")
    def api_identify(body: IdentifyBody):
        out = []
        kd = _keys_dir(settings)
        for raw in body.paths:
            p = Path(raw).expanduser()
            if not p.is_file():
                out.append({"path": raw, "error": "文件不存在"})
                continue
            prof, reason = identify.resolve_game(None, [p], kd)
            if prof is None:
                out.append({"path": str(p), "error": f"无法识别游戏：{reason}",
                            "size": p.stat().st_size})
                continue
            root = _game_root(settings, prof)
            t = identify.direct_target(prof, root, _store(settings, prof), p, None)
            out.append({
                "path": str(p), "game": prof.id, "game_title": prof.title,
                "rel_video": t.rel_video, "source": t.source,
                "method": t.entry_method, "audio": t.entry_audio_hex, "via": t.via,
                "size": p.stat().st_size,
            })
        return {"results": out}

    # ---- 导出 ----
    @app.post("/api/export")
    def api_export(body: ExportBody):
        ffmpeg = _ffmpeg(settings)
        if not ffmpeg:
            raise HTTPException(400, "未找到 ffmpeg：请在设置中指定 ffmpeg.exe 路径")
        paths = [Path(p).expanduser() for p in (body.paths or [])]
        file_paths = [p for p in paths if p.is_file()]
        all_direct = bool(paths) and len(file_paths) == len(paths)
        if paths and not all_direct:
            raise HTTPException(400, f"{len(paths) - len(file_paths)} 个文件不存在或不可读")
        prof = gmod.resolve_game(body.game) if body.game else None
        if prof is None:
            prof = identify.resolve_game(prof, file_paths, _keys_dir(settings))[0]
            if prof is None:
                raise HTTPException(400, "无法识别所属游戏：请分游戏分别导出")
        if body.audio not in ("all", "none") and prof.audio_langs is not None \
                and body.audio not in prof.audio_langs.values():
            raise HTTPException(400, f"未知语言 {body.audio}")

        if all_direct:
            store = _store(settings, prof)
            root = _game_root(settings, prof)
            targets = [identify.direct_target(prof, root, store, p, body.version)
                       for p in file_paths]
        else:
            root = _game_root(settings, prof)
            if root is None:
                raise HTTPException(400, f"未找到 {prof.title} 游戏目录：请在设置中选择")
            from ..export import select_targets
            try:
                targets = select_targets(prof, root, _store(settings, prof),
                                         version=body.version, mode=body.mode or "all",
                                         pattern=body.filter, limit=body.limit,
                                         files=_cache.scan(prof, root))
            except ValueError as exc:
                raise HTTPException(400, str(exc))
        if not targets:
            raise HTTPException(404, "无匹配目标")
        base = Path(body.out_dir).expanduser() if body.out_dir else _default_out(settings)
        out_dir = base.resolve()          # 平铺：直接输出到该目录（文件名已消歧）
        task = manager.submit(prof.id, targets, _make_options(body), out_dir, ffmpeg)
        return {"task_id": task.id, "total": task.total, "out_dir": str(out_dir)}

    def _make_options(body: ExportBody):
        from ..export import Options
        jobs = max(1, min(8, body.jobs or 1))
        return Options(audio=body.audio, audio_format=body.audio_format,
                       container=body.container, verify=body.verify, jobs=jobs)

    # ---- 任务 ----
    @app.get("/api/tasks")
    def api_tasks():
        return {"tasks": [t.summary() for t in manager.list()]}

    @app.get("/api/tasks/{task_id}")
    def api_task(task_id: str):
        task = manager.get(task_id)
        if task is None:
            raise HTTPException(404, "任务不存在")
        return task.summary() | {"results": list(task.results)}

    @app.get("/api/tasks/{task_id}/events")
    def api_task_events(task_id: str, after: int = 0):
        task = manager.get(task_id)
        if task is None:
            raise HTTPException(404, "任务不存在")
        events, index = task.events_after(after)
        return {"events": events, "finished": task.finished is not None, "index": index}

    @app.post("/api/tasks/{task_id}/cancel")
    def api_task_cancel(task_id: str):
        if not manager.cancel(task_id):
            raise HTTPException(404, "任务不存在")
        return {"ok": True}

    @app.delete("/api/tasks/{task_id}")
    def api_task_delete(task_id: str):
        if not manager.delete(task_id):
            raise HTTPException(400, "任务不存在或仍在运行")
        return {"ok": True}

    @app.delete("/api/tasks")
    def api_tasks_clear():
        return {"ok": True, "removed": manager.clear_finished()}

    # ---- 打开文件夹 / 文件 ----
    @app.post("/api/open-folder")
    def api_open_folder(body: OpenBody):
        p = Path(body.path)
        if body.select and p.is_file():
            subprocess.Popen(["explorer", "/select,", str(p)])  # noqa: S603,S607
            return {"ok": True}
        target = p if p.is_dir() else p.parent
        if not target.is_dir():
            raise HTTPException(404, "目录不存在")
        os.startfile(str(target))  # noqa: S606 (Windows 专用，本地工具)
        return {"ok": True}

    @app.post("/api/open-file")
    def api_open_file(body: OpenBody):
        p = Path(body.path)
        if not p.is_file():
            raise HTTPException(404, "文件不存在")
        os.startfile(str(p))  # noqa: S606
        return {"ok": True}

    @app.post("/api/scan-dir")
    def api_scan_dir(body: ScanDirBody):
        d = Path(body.dir).expanduser()
        if not d.is_dir():
            raise HTTPException(400, "目录不存在")
        return {"dir": str(d), "files": _expand_usm([str(d)])}

    # ---- 密钥更新 ----
    @app.post("/api/keys/update")
    def api_keys_update(body: KeysUpdateBody):
        base = (body.url or settings.key_update_url or "").strip().rstrip("/")
        if not base:
            raise HTTPException(400, "未配置密钥更新源：请在设置中填写 raw 目录 URL")
        user_dir = user_keys_dir()
        backup = app_data_dir() / "keys_backup" / time.strftime("%Y%m%d-%H%M%S")
        fetched = {}
        try:
            for name in KEY_FILES:
                url = f"{base}/{name}"
                with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
                    data = resp.read()
                parsed = json.loads(data.decode("utf-8"))
                if not isinstance(parsed, dict):
                    raise ValueError(f"{name} 结构异常")
                fetched[name] = data
        except Exception as exc:
            raise HTTPException(502, f"下载失败：{exc}（更新源：{base}）")
        # 全部下载成功才落盘：先备份当前 → 替换
        backup.mkdir(parents=True, exist_ok=True)
        for name, data in fetched.items():
            cur = user_dir / name
            if cur.is_file():
                shutil.copy2(cur, backup / name)
            cur.write_bytes(data)
        _cache.clear()
        stats = {}
        for name in KEY_FILES:
            p = user_dir / name
            if p.is_file():
                try:
                    stats[name] = len(json.loads(p.read_text(encoding="utf-8")))
                except Exception:
                    stats[name] = None
        return {"ok": True, "target_dir": str(user_dir), "backup": str(backup),
                "counts": stats}

    @app.get("/api/keys/backups")
    def api_keys_backups():
        d = app_data_dir() / "keys_backup"
        items = sorted((p.name for p in d.iterdir() if p.is_dir()), reverse=True) if d.is_dir() else []
        return {"backups": items}

    @app.post("/api/keys/rollback")
    def api_keys_rollback(body: ScanDirBody):
        """回滚到某个备份（body.dir = 备份名）；"bundled" = 删除用户副本回到随包快照。"""
        user_dir = app_data_dir() / "keys"
        if body.dir == "bundled":
            if user_dir.is_dir():
                shutil.rmtree(user_dir)
            _cache.clear()
            return {"ok": True}
        src = app_data_dir() / "keys_backup" / Path(body.dir).name
        if not src.is_dir():
            raise HTTPException(404, "备份不存在")
        user_dir.mkdir(parents=True, exist_ok=True)
        for f in src.glob("*.json"):
            shutil.copy2(f, user_dir / f.name)
        _cache.clear()
        return {"ok": True}

    # ---- 静态前端（挂载在最后，/api 路由优先） ----
    dist = Path(__file__).resolve().parent / "dist"
    if dist.is_dir() and (dist / "index.html").is_file():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    else:
        @app.get("/")
        def index():
            return {"message": "前端未构建：在 web/ 目录运行 npm install && npm run build"}

    return app
