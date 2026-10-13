# -*- coding: utf-8 -*-
"""SD3.5 Large Q4 GGUF 실전 테스트 v3 (RAM·VRAM 안전 버전)
- GGUF를 dict로 1회 파싱 → pos_embed 차원만 수정 → from_single_file(dict)
- low_cpu_mem_usage=True (meta init) → RAM 16GB 초과 방지
- T5(text_encoder_3) 제외, CLIP-L/CLIP-G/VAE만 다운로드(게이트 레포, HF 토큰 사용)
- 생성: 512x896 안전 검증 → 성공 시 576x1024 도전은 결과 보고 결정
사용법: python scripts/test_sd35_gguf.py
"""
import os, sys, time, gc
from pathlib import Path

os.environ["HF_HOME"] = str(Path(__file__).resolve().parents[1] / "model" / ".cache")  # 반드시 diffusers import 전
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GGUF = str(Path(__file__).resolve().parents[1] / "model" / "sd3.5_large-q4_k_4_0.gguf")
CONFIG_REPO = "stabilityai/stable-diffusion-3.5-large"
OUT_DIR = r"output\images"
H, W, STEPS, GUID = 896, 512, 28, 4.5  # 512x896 안전 버전 (576x1024는 이후)
PROMPT = (
    "a cute cartoon astronaut cat floating in a colorful space nebula, "
    "vibrant cartoon illustration, bright vivid colors, vertical 9:16 portrait, high quality"
)

# ---- RAM 가드 ----
try:
    import psutil
    avail = psutil.virtual_memory().available / 1024**3
    print(f"▶ RAM 여유: {avail:.1f}GB / 총 {psutil.virtual_memory().total / 1024**3:.1f}GB")
    if avail < 3:
        print("❌ RAM 여유 부족 — 중단합니다.")
        sys.exit(1)
except Exception:
    pass

# ---- HF 토큰 ----
_TOKEN = None
for _p in (os.path.expanduser(r"~\.cache\huggingface\token"), os.path.expanduser(r"~\.huggingface\token")):
    if os.path.exists(_p):
        _TOKEN = open(_p, encoding="utf-8").read().strip()
        os.environ["HF_TOKEN"] = _TOKEN
        break
if not _TOKEN:
    print("⚠️ HF 토큰 없음 — 게이트 레포 접근 불가")
    sys.exit(1)

import torch
from PIL import Image
from diffusers import SD3Transformer2DModel, StableDiffusion3Pipeline
from diffusers.quantizers.quantization_config import GGUFQuantizationConfig
from diffusers.models.model_loading_utils import load_gguf_checkpoint
import huggingface_hub as hh, shutil

t_start = time.time()
print(f"▶ 시작: {time.strftime('%H:%M:%S')}")

# ---- 0) transformer config.json 로컬 사용 (qk_norm=None 이미 적용됨) ----
cfg_dir = str(Path(__file__).resolve().parents[1] / "model" / "sd35_cfg")
os.makedirs(cfg_dir, exist_ok=True)
if not os.path.exists(os.path.join(cfg_dir, "config.json")):
    _src = hh.hf_hub_download(CONFIG_REPO, "config.json", subfolder="transformer", token=_TOKEN)
    shutil.copy(_src, os.path.join(cfg_dir, "config.json"))
    # qk_norm 비활성화 (GGUF 차원 불일치 우회)
    import json
    _cfg = json.load(open(os.path.join(cfg_dir, "config.json"), encoding="utf-8"))
    _cfg["qk_norm"] = None
    json.dump(_cfg, open(os.path.join(cfg_dir, "config.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print("✅ config.json 준비 (qk_norm=None)", flush=True)

# ---- 1) GGUF 파싱 (1회) + pos_embed 차원 수정 ----
# 주의: sdcpp GGUF의 키는 `model.diffusion_model.pos_embed` (접미사 없음).
# diffusers는 로드 시 `pos_embed.pos_embed`로 재매핑하며 차원은 그대로 → [36864,2432]
print("▶ GGUF 파싱 중...", flush=True)
ckpt = load_gguf_checkpoint(GGUF)
_pe = ckpt.get("model.diffusion_model.pos_embed")
if _pe is not None and getattr(_pe, "dim", lambda: 0)() == 2:
    ckpt["model.diffusion_model.pos_embed"] = _pe.unsqueeze(0)
    print(f"✅ pos_embed 차원 수정: [{','.join(map(str, _pe.shape))}] "
          f"→ [{','.join(map(str, _pe.unsqueeze(0).shape))}]", flush=True)
else:
    print("⚠️ pos_embed 형상 이상 — 그대로 진행", flush=True)

# ---- 2) 트랜스포머 (MMDiT, Q4) meta init + 양자화 웨이트 ----
# qk_norm=None 설정으로 norm_q/norm_k 레이어 자체가 생성되지 않음.
print("▶ 트랜스포머 로드 중 (Q4, meta 초기화)...", flush=True)
_qcfg = GGUFQuantizationConfig(compute_dtype=torch.float16)
transformer = SD3Transformer2DModel.from_single_file(
    ckpt,
    config=cfg_dir,
    quantization_config=_qcfg,
    torch_dtype=torch.float16,
    token=_TOKEN,
    low_cpu_mem_usage=True,
)
del ckpt
gc.collect()
print(f"✅ 1) 트랜스포머 Q4 로드 완료: {time.time() - t_start:.0f}s", flush=True)

# ---- 1-2) qk-norm 비활성화됨 (qk_norm=None) ----
# GGUF의 ln_q/ln_k 차원(36)이 config(head_dim=64)와 불일치하므로 qk_norm 스킵.
# __torch_function__ 패치는 is_floating_point()를 깨뜨려 제거함.
# (기존 패치: cat/mul/view 누출 방지였으나 pipe.to("cuda")에서 오류 유발)

# ---- 3) 파이프라인 조립 (CLIP-L/CLIP-G/VAE 다운로드, T5 제외) ----
print("▶ 파이프라인 조립 (CLIP+VAE ~2GB 첫 다운로드)...", flush=True)
pipe = StableDiffusion3Pipeline.from_pretrained(
    CONFIG_REPO,
    transformer=transformer,
    text_encoder_3=None,
    tokenizer_3=None,
    torch_dtype=torch.float16,
    token=_TOKEN,
)
print(f"✅ 2) 파이프라인 완료: {time.time() - t_start:.0f}s", flush=True)

pipe.to("cuda")
try:
    pipe.enable_vae_tiling()
except Exception as e:
    print(f"  (vae_tiling 생략: {e})")
print(f"  CUDA: {torch.cuda.get_device_name(0)} / 사용 전 VRAM {torch.cuda.memory_allocated()/1024**3:.2f}GB", flush=True)

# ---- 4) 생성 ----
print(f"▶ 생성 시작: {W}x{H}, {STEPS}스텝, guidance {GUID} — {time.strftime('%H:%M:%S')}", flush=True)
t_gen = time.time()
try:
    with torch.inference_mode():
        image = pipe(prompt=PROMPT, height=H, width=W, num_inference_steps=STEPS, guidance_scale=GUID).images[0]
    dt = time.time() - t_gen
    print(f"⏱️ 생성 완료: {dt:.1f}s ({dt/STEPS:.2f}s/스텝)", flush=True)
except torch.cuda.OutOfMemoryError as e:
    print(f"❌ CUDA OOM: {e}", flush=True)
    sys.exit(2)

os.makedirs(OUT_DIR, exist_ok=True)
out = os.path.join(OUT_DIR, "sd35_test_01.png")
image = image.resize((1080, 1920), Image.LANCZOS)
image.save(out)
print(f"✅ 저장: {out} ({os.path.getsize(out)//1024}KB)", flush=True)

print("\n--- 측정 결과 ---")
print(f"VRAM peak : {torch.cuda.max_memory_allocated()/1024**3:.2f}GB / 11.0GB 한도")
print(f"로드 {time.time()-t_start-dt:.0f}s + 생성 {dt:.0f}s = 총 {time.time()-t_start:.0f}s")
print("TEST OK", flush=True)