# -*- coding: utf-8 -*-
"""GPU / VRAM detection and image-generation mode recommendation.

Why: only ONE step of the pipeline needs a GPU (local image generation).
     Everything else (script, bubbles, narration, video, upload) runs on CPU.

Output is ASCII-only on purpose: this script is called from install.bat /
doctor.bat where non-ASCII text can break the cmd parser.

Usage:
    python scripts\\check_gpu.py              # human readable report
    python scripts\\check_gpu.py --json       # machine readable (for .bat)
    python scripts\\check_gpu.py --download   # download the recommended model
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MODEL_DIR = ROOT / "model"

SDXL_DIR = MODEL_DIR / "sdxl-turbo"
GGUF_REPO = "city96/stable-diffusion-3.5-large-turbo-GGUF"
GGUF_FILE = "sd3.5_large_turbo-Q4_0.gguf"

MANUAL_MODE_HOWTO = [
    "Manual image mode (no GPU needed):",
    "  1) run start_web.bat",
    "  2) tab 2: 'use another image -> register as base'  (upload your own picture)",
    "  3) or tab 3: 'skip'  (keep the existing image)",
    "  Everything else (script / bubbles / narration / video / upload) works on CPU.",
]


def nvidia_info():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        r = subprocess.run(
            [exe, "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    parts = [p.strip() for p in r.stdout.strip().splitlines()[0].split(",")]
    if len(parts) < 3:
        return None
    try:
        vram = int(float(parts[1]))
    except ValueError:
        vram = 0
    return {"name": parts[0], "memory_mb": vram, "driver": parts[2]}


def torch_info():
    try:
        import torch
    except Exception as exc:                      # torch not installed
        return {"installed": False, "error": str(exc)[:100]}
    info = {
        "installed": True,
        "version": torch.__version__,
        "cuda_available": bool(torch.cuda.is_available()),
        "cuda_version": torch.version.cuda,
        "device_name": None,
    }
    if info["cuda_available"]:
        try:
            info["device_name"] = torch.cuda.get_device_name(0)
        except Exception:
            pass
    return info


def model_files():
    gguf = sorted(p.name for p in MODEL_DIR.glob("*.gguf")) if MODEL_DIR.exists() else []
    return {
        "sdxl_turbo": (SDXL_DIR / "model_index.json").exists(),
        "gguf": gguf,
    }


def hf_token_present():
    if os.environ.get("HF_TOKEN", "").strip():
        return True
    for cand in (ROOT / "hf_token.txt", Path.home() / ".cache" / "huggingface" / "token"):
        try:
            if cand.exists() and cand.read_text(encoding="utf-8", errors="ignore").strip():
                return True
        except Exception:
            pass
    return False


def decide(gpu, torch, files, has_token):
    vram = (gpu or {}).get("memory_mb", 0)
    cuda_ok = bool(torch.get("installed") and torch.get("cuda_available"))

    if files["gguf"] and cuda_ok and (vram >= 11000 or vram == 0):
        return "sd35_gguf", "GGUF file already present (best quality, ~31s/image on 11GB)"
    if files["sdxl_turbo"] and cuda_ok:
        return "sdxl_turbo", "SDXL-Turbo already present (~43s/image)"
    if not cuda_ok:
        return "manual", "no CUDA GPU detected"
    if vram and vram < 8000:
        return "manual", "VRAM below 8GB"
    if vram < 11000:
        return "sdxl_turbo", "8-10GB VRAM -> SDXL-Turbo (13GB, no HF token needed)"
    if not has_token:
        return "sdxl_turbo", "11GB+ VRAM but no HF token -> SDXL-Turbo instead (SD3.5 needs a gated repo token)"
    return "sd35_gguf", "11GB+ VRAM -> SD3.5 Large Turbo Q4 GGUF (~31s/image)"


def download(mode):
    if mode == "sdxl_turbo":
        print("[download] SDXL-Turbo (stabilityai/sdxl-turbo, ~13GB) ...", flush=True)
        return subprocess.call([sys.executable, "-X", "utf8",
                                str(ROOT / "scripts" / "download_sdxl.py")])
    if mode == "sd35_gguf":
        print(f"[download] {GGUF_REPO}/{GGUF_FILE} (~4.8GB) ...", flush=True)
        from huggingface_hub import snapshot_download
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        snapshot_download(repo_id=GGUF_REPO, allow_patterns=[GGUF_FILE],
                          local_dir=str(MODEL_DIR), local_dir_use_symlinks=False,
                          resume_download=True)
        target = MODEL_DIR / GGUF_FILE
        print("[download] done:", target, flush=True)
        print("[env] add this line to .env so the program uses this file:", flush=True)
        print(f"SD_GGUF_CHECKPOINT={target}", flush=True)
        return 0
    print("[download] nothing to download (manual image mode)", flush=True)
    print("\n".join(MANUAL_MODE_HOWTO), flush=True)
    return 0


def main():
    ap = argparse.ArgumentParser(description="GPU check and image mode recommendation")
    ap.add_argument("--json", action="store_true", help="print JSON only")
    ap.add_argument("--download", action="store_true", help="download recommended model")
    args = ap.parse_args()

    gpu = nvidia_info()
    torch = torch_info()
    files = model_files()
    has_token = hf_token_present()
    mode, reason = decide(gpu, torch, files, has_token)

    result = {
        "gpu": gpu,
        "torch": torch,
        "models": files,
        "hf_token": has_token,
        "mode": mode,
        "reason": reason,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return 0

    print("=" * 62)
    print(" GPU / image generation check")
    print("=" * 62)
    if gpu:
        print(f" GPU          : {gpu['name']}")
        print(f" VRAM         : {gpu['memory_mb']} MB")
        print(f" Driver       : {gpu['driver']}")
    else:
        print(" GPU          : nvidia-smi not found (no NVIDIA driver / not NVIDIA)")
    if torch.get("installed"):
        print(f" torch        : {torch['version']}"
              f"  (cuda={torch['cuda_available']}, cuda_ver={torch['cuda_version']})")
    else:
        print(f" torch        : NOT installed ({torch.get('error')})")
    print(f" SDXL-Turbo   : {'present' if files['sdxl_turbo'] else 'missing'}")
    print(f" GGUF files   : {', '.join(files['gguf']) if files['gguf'] else 'none'}")
    print(f" HF token     : {'yes' if has_token else 'no'}")
    print("-" * 62)
    print(f" RECOMMENDED  : {mode}")
    print(f" why          : {reason}")
    print("-" * 62)
    if mode == "manual":
        print("\n".join(MANUAL_MODE_HOWTO))
    else:
        print(" next         : install.bat downloads this model automatically")
        print("                (or run: python scripts\\check_gpu.py --download)")

    if args.download:
        print("-" * 62)
        return download(mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())

