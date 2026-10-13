# -*- coding: utf-8 -*-
"""Diagnostics: collect environment info into doctor_report.txt.

Attach that file to a GitHub issue - it answers most "it does not work" questions
in one round trip. Output is ASCII-only because it is called from doctor.bat.
Secrets are never printed (only whether a key is set or empty).

Usage:
    python scripts\\doctor.py
"""
import ctypes
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MODEL_DIR = ROOT / "model"
PORT = int(os.environ.get("WEBAPP_PORT", "8765"))
KEY_NAMES = {"GEMINI_API_KEY", "GROQ_API_KEY", "OUTROUTER_API_KEY", "NVIDIA_API_KEY",
             "HF_TOKEN", "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"}


class Report:
    def __init__(self):
        self.lines = []

    def add(self, text=""):
        self.lines.append(text)
        print(text, flush=True)

    def item(self, label, value):
        self.add(f"  {label:<20}: {value}")


def run(cmd, timeout=120):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return ((r.stdout or "") + (r.stderr or "")).strip() or "(no output)"
    except FileNotFoundError:
        return "NOT FOUND"
    except Exception as exc:
        return f"ERROR: {exc}"


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def ram_text():
    try:
        st = MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
        return f"{st.ullTotalPhys / 1e9:.1f} GB total / {st.ullAvailPhys / 1e9:.1f} GB free"
    except Exception as exc:
        return f"unknown ({exc})"


def env_text():
    env = ROOT / ".env"
    if not env.exists():
        return "no .env file (copy .env.example to .env)"
    found = []
    for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        if key in KEY_NAMES:
            found.append(f"{key}={'set' if val.strip() else 'empty'}")
    return ", ".join(found) or "no known keys inside .env"


def port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex(("127.0.0.1", port)) != 0


def main():
    r = Report()
    r.add("=" * 66)
    r.add(" YouTube Shorts Studio - doctor report")
    r.add(f" generated: {__import__('datetime').datetime.now():%Y-%m-%d %H:%M:%S}")
    r.add(f" project  : {ROOT}")
    r.add("=" * 66)

    r.add("[1] System")
    r.item("OS", f"{platform.system()} {platform.release()} ({platform.version()})")
    r.item("CPU", platform.processor() or "unknown")
    r.item("RAM", ram_text())

    r.add("[2] Python / venv")
    r.item("python", f"{platform.python_version()}  ({sys.executable})")
    r.item("venv python", "present" if (ROOT / "venv" / "Scripts" / "python.exe").exists() else "missing")

    r.add("[3] torch / CUDA")
    r.add("  " + run([sys.executable, "-c",
                      "import torch;print('torch',torch.__version__,'cuda',torch.cuda.is_available(),"
                      "'cuda_ver',torch.version.cuda)"]))
    r.add("[3-1] edge-tts (음성 합성)")
    r.add("  " + run([sys.executable, "-c",
                      "import edge_tts;v=getattr(edge_tts,'__version__','0');"
                      "p=tuple(int(x) for x in v.split('.')[:3] if x.isdigit());"
                      "print('edge-tts',v,'OK' if p>=(7,3,1) else 'TOO OLD (need 7.3.1+) - pip install -U edge-tts')"]))

    r.add("[4] NVIDIA driver")
    r.add("  " + run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                      "--format=csv,noheader"]))

    r.add("[5] FFmpeg")
    r.item("ffmpeg", run(["ffmpeg", "-version"]).splitlines()[0] if run(["ffmpeg", "-version"]).strip() else "?")
    r.item("ffprobe", run(["ffprobe", "-version"]).splitlines()[0] if run(["ffprobe", "-version"]).strip() else "?")

    r.add("[6] NVENC (GPU encoder) - CPU fallback is normal")
    r.add("  " + run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "check_nvenc.py")])[:600])

    r.add("[7] Local models")
    sdxl = MODEL_DIR / "sdxl-turbo" / "model_index.json"
    r.item("sdxl-turbo", "present" if sdxl.exists() else "missing")
    ggufs = sorted(MODEL_DIR.glob("*.gguf")) if MODEL_DIR.exists() else []
    r.item("gguf files", ", ".join(f"{p.name} ({p.stat().st_size / 1e9:.2f} GB)" for p in ggufs) or "none")

    r.add("[8] .env keys (values are never printed)")
    r.add("  " + env_text())

    r.add("[9] YouTube credentials")
    r.item("client_secret.json", "present" if (ROOT / "client_secret.json").exists() else "missing")
    r.item("token.pickle", "present" if (ROOT / "token.pickle").exists() else "missing")

    r.add("[10] token status")
    r.add("  " + run([sys.executable, "-X", "utf8", str(ROOT / "check_token.py")])[:500])

    r.add("[11] Disk space")
    try:
        usage = shutil.disk_usage(ROOT)
        r.item("free", f"{usage.free / 1e9:.1f} GB free / {usage.total / 1e9:.1f} GB total")
    except Exception as exc:
        r.item("free", f"unknown ({exc})")

    r.add("[12] Web editor port")
    r.item(f"port {PORT}", "free" if port_free(PORT) else "already in use (close the other app)")

    r.add("=" * 66)
    r.add(" Next: attach doctor_report.txt to your issue.")
    r.add("=" * 66)

    out = ROOT / "doctor_report.txt"
    out.write_text("\n".join(r.lines) + "\n", encoding="utf-8")
    print(f"\n[ok] report written: {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
