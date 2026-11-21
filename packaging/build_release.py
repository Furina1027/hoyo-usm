"""便携版组装脚本：PyInstaller 产物 + portable.ini + ffmpeg → zip。

用法（仓库根目录）：
    python packaging/build_release.py            # 构建 + 组装 + zip
    python packaging/build_release.py --no-zip   # 只组装目录（便于冒烟）

前置：
  * web/ 前端已构建（hoyo_usm/gui/dist 存在）
  * PyInstaller 已安装（pip install pyinstaller）
  * ffmpeg 静态构建 zip 已在 packaging/_cache/ffmpeg.zip
    （下载：https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip）
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(__file__).resolve().parent / "_cache"


def version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def ensure_frontend() -> None:
    dist = ROOT / "hoyo_usm" / "gui" / "dist"
    if not (dist / "index.html").is_file():
        print("[!] 前端未构建：cd web && npm install && npm run build", file=sys.stderr)
        sys.exit(1)


def ensure_ffmpeg() -> Path:
    """定位可捆绑的静态 ffmpeg.exe。

    顺序：_cache/ffmpeg.exe → _cache/*.zip 提取 → 系统 PATH（本机已装，
    静态单文件可直接随包分发）。发布构建建议优先放置官方静态构建 zip。
    """
    out = CACHE / "ffmpeg.exe"
    if out.is_file():
        return out
    zips = list(CACHE.glob("*.zip"))
    if zips:
        with zipfile.ZipFile(zips[0]) as z:
            members = [n for n in z.namelist() if n.endswith("/ffmpeg.exe") or n == "ffmpeg.exe"]
            if members:
                with z.open(members[0]) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                print(f"[+] ffmpeg.exe 已从 zip 提取（{out.stat().st_size // (1024*1024)} MB）")
                return out
    which = shutil.which("ffmpeg")
    if which:
        src = Path(which)
        shutil.copy2(src, out)
        print(f"[+] 使用系统 ffmpeg：{src}（{out.stat().st_size // (1024*1024)} MB）")
        return out
    print("[!] 找不到 ffmpeg：下载静态构建放到\n"
          f"    {CACHE}\\ffmpeg.zip\n"
          "    （https://github.com/BtbN/FFmpeg-Builds/releases）", file=sys.stderr)
    sys.exit(1)


def run_pyinstaller() -> Path:
    out_dir = ROOT / "packaging" / "dist"
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "packaging/hoyo-usm-gui.spec",
         "--noconfirm", "--distpath", str(out_dir),
         "--workpath", str(ROOT / "packaging" / "build")],
        check=True, cwd=str(ROOT),
    )
    built = out_dir / "hoyo-usm-gui"
    if not (built / "hoyo-usm-gui.exe").is_file():
        print("[!] PyInstaller 产物缺失", file=sys.stderr)
        sys.exit(1)
    return built


def assemble(ffmpeg_exe: Path, ver: str, no_zip: bool) -> Path:
    release = ROOT / "release"
    target = release / f"hoyo-usm-gui-portable-{ver}"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    # PyInstaller onedir 产物整体拷入
    shutil.copytree(ROOT / "packaging" / "dist" / "hoyo-usm-gui", target, dirs_exist_ok=True)
    # 便携标记 + ffmpeg
    (target / "portable.ini").write_text("", encoding="utf-8")
    fdir = target / "ffmpeg"
    fdir.mkdir(exist_ok=True)
    shutil.copy2(ffmpeg_exe, fdir / "ffmpeg.exe")
    # keys 已在 _internal/keys（spec datas），无需重复拷贝
    print(f"[+] 便携版目录：{target}")
    if not no_zip:
        zpath = release / f"hoyo-usm-gui-portable-{ver}.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for p in sorted(target.rglob("*")):
                z.write(p, p.relative_to(target.parent))
        print(f"[+] 便携版 zip：{zpath}（{zpath.stat().st_size // (1024*1024)} MB）")
    return target


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-zip", action="store_true", help="只组装目录，不打 zip")
    ap.add_argument("--skip-build", action="store_true", help="跳过 PyInstaller（复用上次产物）")
    args = ap.parse_args()

    ensure_frontend()
    ffmpeg_exe = ensure_ffmpeg()
    if not args.skip_build:
        run_pyinstaller()
    assemble(ffmpeg_exe, version(), args.no_zip)


if __name__ == "__main__":
    main()
