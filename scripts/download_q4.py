"""SD3.5 Large Q4_K_4_0 GGUF downloader (resumable, public repo)."""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
from huggingface_hub import snapshot_download

REPO = "stduhpf/SD3.5-Large-GGUF-mixed-sdcpp"
FILE = "sd3.5_large-q4_k_4_0.gguf"
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
