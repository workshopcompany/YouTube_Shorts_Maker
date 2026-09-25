"""SD3.5 Large FP8 downloader (resumable, public repo, no login needed)."""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
from huggingface_hub import snapshot_download

REPO = "Comfy-Org/stable-diffusion-3.5-fp8"
FILE = "sd3.5_large_fp8_scaled.safetensors"
DEST = Path(__file__).resolve().parents[1] / "model"
DEST.mkdir(parents=True, exist_ok=True)

print(f"Downloading {REPO}/{FILE} -> {DEST} ...", flush=True)
p = snapshot_download(
    repo_id=REPO,
    allow_patterns=[FILE],
    local_dir=str(DEST),
    local_dir_use_symlinks=False,
    resume_download=True,
)
print(f"[OK] done: {p}", flush=True)
import os
fp = DEST / FILE
if fp.exists():
    print(f"size={fp.stat().st_size/1e9:.2f}GB", flush=True)
