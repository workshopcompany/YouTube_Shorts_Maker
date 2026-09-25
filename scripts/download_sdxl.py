"""SDXL-Turbo resume downloader (cleans stale locks, resumable)."""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
from huggingface_hub import snapshot_download

REPO = "stabilityai/sdxl-turbo"
DEST = Path(__file__).resolve().parents[1] / "model" / "sdxl-turbo"
DEST.mkdir(parents=True, exist_ok=True)

# stale lock files from killed run -> remove so new run is clean
for lock in DEST.rglob("*.lock"):
    try:
        lock.unlink()
        print(f"removed lock: {lock}", flush=True)
    except Exception as e:
        print(f"lock skip {lock}: {e}", flush=True)

print(f"Downloading {REPO} -> {DEST} ...", flush=True)
p = snapshot_download(
    repo_id=REPO,
    local_dir=str(DEST),
    local_dir_use_symlinks=False,
    resume_download=True,
)
print(f"[OK] done: {p}", flush=True)
