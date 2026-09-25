# -*- coding: utf-8 -*-
"""Download FFmpeg (BtbN win64 GPL build) into <project>/ffmpeg8.

FFmpeg is NOT shipped with this repository (GPL / size), so install.bat runs this
once on the user's machine. Output is ASCII-only because it is called from .bat.

Usage:
    python scripts\\download_ffmpeg.py
    python scripts\\download_ffmpeg.py --force     # re-download the zip
"""
import argparse
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "ffmpeg8"
DEFAULT_BIN = DEST / "ffmpeg-n8.1-latest-win64-gpl-8.1" / "bin"
API = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/tags/latest"
UA = {"User-Agent": "shorts-studio-installer"}


def pick_asset():
    req = urllib.request.Request(API, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    cands = []
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if "win64-gpl" in name and name.endswith(".zip"):
            m = re.search(r"ffmpeg-n(\d+)\.(\d+)", name)
            key = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
            cands.append((key, name, asset["browser_download_url"], asset.get("size", 0)))
    if not cands:
        raise RuntimeError("no win64-gpl .zip asset found in the BtbN release")
    cands.sort(reverse=True)
    return cands[0]


def find_ffmpeg():
    for exe in DEST.rglob("ffmpeg.exe"):
        return exe.parent
    return None


def download(url, target, size_hint=0):
    part = target.with_suffix(target.suffix + ".part")
    pos = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers=UA)
    if pos:
        req.add_header("Range", f"bytes={pos}-")
        print(f"  resuming from {pos / 1e6:.1f} MB", flush=True)
    with urllib.request.urlopen(req, timeout=120) as resp:
        resumed = pos if resp.status == 206 else 0
        if pos and not resumed:
            print("  server ignored the resume request - restarting", flush=True)
        mode = "ab" if resumed else "wb"
        total = int(resp.headers.get("Content-Length", 0)) + resumed
        done = resumed
        with open(part, mode) as fh:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done / 1e6:7.1f} / {total / 1e6:7.1f} MB", end="", flush=True)
    print(flush=True)
    part.replace(target)


def extract(zip_path):
    DEST.mkdir(parents=True, exist_ok=True)
    print(f"  extracting {zip_path.name} ...", flush=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(DEST)
    return find_ffmpeg()


def sync_env(bin_dir):
    """If the extracted folder is not the config default, remember it in .env."""
    if bin_dir == DEFAULT_BIN:
        print("[env] path matches the default - no .env change needed", flush=True)
        return
    env = ROOT / ".env"
    if not env.exists():
        example = ROOT / ".env.example"
        env.write_text(example.read_text(encoding="utf-8") if example.exists() else "",
                       encoding="utf-8", newline="\r\n")
    lines = env.read_text(encoding="utf-8", errors="replace").splitlines()
    kept = [ln for ln in lines if not ln.strip().startswith("FFMPEG_DIR=")]
    kept.append(f"FFMPEG_DIR={bin_dir}")
    env.write_text("\n".join(kept) + "\n", encoding="utf-8", newline="\r\n")
    print(f"[env] FFMPEG_DIR added to .env -> {bin_dir}", flush=True)


def main():
    ap = argparse.ArgumentParser(description="download FFmpeg into ./ffmpeg8")
    ap.add_argument("--force", action="store_true", help="re-download even if ffmpeg.exe exists")
    args = ap.parse_args()

    found = find_ffmpeg()
    if found and not args.force:
        print(f"[skip] ffmpeg already present: {found}", flush=True)
        sync_env(found)
        return 0

    try:
        ver, name, url, size = pick_asset()
    except Exception as exc:
        print(f"[ERROR] cannot query the BtbN release list: {exc}", flush=True)
        print("        install FFmpeg manually (https://www.gyan.dev/ffmpeg/builds/)", flush=True)
        print("        and add its bin folder to PATH, or set FFMPEG_DIR in .env", flush=True)
        return 1

    print(f"[info] asset: {name} ({size / 1e6:.0f} MB)", flush=True)
    zip_path = DEST / name
    DEST.mkdir(parents=True, exist_ok=True)
    if not zip_path.exists() or args.force:
        download(url, zip_path, size)
    else:
        print("  zip already downloaded", flush=True)

    bin_dir = extract(zip_path)
    if not bin_dir:
        print("[ERROR] ffmpeg.exe not found after extraction", flush=True)
        return 1
    print(f"[ok] ffmpeg ready: {bin_dir}", flush=True)
    sync_env(bin_dir)
    try:
        zip_path.unlink()
        print("  zip removed to save disk space", flush=True)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
