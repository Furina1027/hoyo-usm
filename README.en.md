# hoyo-usm

English | [简体中文](README.md)

Losslessly decrypts and exports cutscenes (CRI USM containers) from **Genshin Impact (gi) /
Honkai: Star Rail (hsr) / Zenless Zone Zero (zzz)**. Ships as a desktop GUI and a CLI.
Reads only game files already on your machine and runs fully offline.

## Portable build (recommended)

`release/hoyo-usm-gui-portable-<version>.zip` is a portable, install-free build
(produced by `python packaging/build_release.py`; ffmpeg and the key snapshot are bundled):

1. Extract anywhere and run `hoyo-usm-gui.exe`
2. Settings and exports live in the `config/` folder next to the exe — delete the folder to fully uninstall
3. Requires the WebView2 runtime (built into Windows 11, usually present on Windows 10)
4. Optional flags: `--browser` (browser mode), `--port=8788`, `--no-open` (serve without opening a window)

## What it does

- Parses USM containers; supports both cipher generations (legacy feedback XOR mask / AES-128-CTR)
- Copies the video stream **bit-exact** (codec copy) — no re-encoding, no quality loss
- Decodes audio (HCA / ADX) to PCM and muxes as **FLAC / WAV / AAC**, or bypasses the raw stream
- Multi-language audio: export all four tracks (with language tags) or a single track
- Containers **MP4 / MKV / WebM**, chosen automatically per codec or set manually
- Optional full ffmpeg decode verification after export
- Batch export: filter by version additions/updates, by filename wildcard, multi-process parallelism, with an export report
- For .usm files outside the game directory, recovers the original path and key by content md5

## Install

Requires Python 3.11+; exporting needs numpy / pycryptodome / cricodecs / ffmpeg.

```bash
pip install -e .
pip install -e ".[gui]"        # GUI extras: fastapi / uvicorn / pywebview
```

## Usage

### CLI

```bash
hoyo-usm check                        # self-check: environment, key store, game folders
hoyo-usm status --game zzz            # local files × key coverage
hoyo-usm list --game gi --mode new    # files changed in a version
hoyo-usm probe <file.usm>             # read-only parse: container / cipher / pipeline
hoyo-usm export --game zzz --audio none          # batch export by mode
hoyo-usm export --game gi "C:\path\xxx.usm" --audio all   # explicit files (--game optional)

# GUI (local web service + native window; --browser falls back to the browser)
hoyo-usm gui
```

`--game` accepts `gi` / `hsr` / `zzz`.

### GUI

`hoyo-usm gui` starts a local service (binds to 127.0.0.1 only) and opens the app window:

- **First-run wizard**: detects installed games (registry + drive scan) with instant path validation
- **Overview**: per-game file counts, total size, decryptable ratio by cipher type, latest-version additions
- **Game files**: virtualized table with instant search, version/cipher filters, column sorting,
  shift-range selection and keyboard navigation; a detail panel shows video / audio / key / pipeline
- **Export tasks**: live progress with ETA, task queue, persisted history, per-file results with play/reveal
- **External files**: drag files or folders into the window; games and keys are identified automatically
- **Settings**: game folders / ffmpeg / output (native browse dialogs + validation), key-store update & rollback,
  dark / light / system theme


## Keys

A key snapshot ships with the repository in `keys/` (provenance and stats in `keys/PROVENANCE.md`);
runtime needs no external services. After game updates you can pull the latest snapshot from an
update URL in the GUI settings (auto-backed-up, rollback supported).

## Disclaimer

For personal study and viewing only; do not redistribute exported content.
This project is not affiliated with miHoYo / HoYoverse.

## License

MIT
