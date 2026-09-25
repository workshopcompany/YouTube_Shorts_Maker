# 🖼️ SD 3.5 Large Turbo (GGUF Q4) 이미지 생성 설정 보고서

| 항목 | 내용 |
|---|---|
| **작성일** | 2026-09-16 |
| **상태** | ✅ 완성 — 모자이크 문제 해결, 실사용 검증 완료 |
| **환경** | Windows 11 / GTX 1080Ti 11GB (sm_61) / torch 2.5.1+cu118 / venv |
| **모델** | `model/sd3.5_large_turbo-q4_k_4_0.gguf` (4.87GB, Q4_0 양자화 단일파일) |
| **성능** | 로드 약 12초(transformer) / **장당 약 31초**(8 steps) / VRAM peak **7.78GB / 11GB** |

---

## 1. 도입 배경

- Gemini 3.1-flash-image API가 **429 쿼터 초과**로 잦은 실패 → 실전 사용 불가
- API 의존을 끊고 **완전 무료·오프라인** 로컬 이미지 생성 확보가 목표
- 1080Ti 11GB VRAM에 맞는 선택지로 **SD 3.5 Large Turbo Q4 GGUF** 채택
  - Turbo = 8 steps 저스텝 추론 (guidance_scale=0.0 필수)
  - GGUF Q4 = 4.87GB로 양자화되어 fp16 full(약 16GB) 대비 VRAM 부담 1/3
- SDXL-Turbo(1번 메뉴, 43초/장) 대비 화질·문자표현 우수하고 더 빠름

---

## 2. 최종 동작 구조

```
[로드 시 1회, 약 12~15초]
scripts/gguf_patch.py → apply()
  └ diffusers 내부 load_gguf_checkpoint 몽키패치
     (1) QK-norm(ln_q/ln_k) Q4_0 raw → fp32 평문 디퀀타이즈 (152개 텐서)
     (2) pos_embed [36864,2432] → [1,36864,2432] 배치차원 추가

modules/image_gen.py::_load_sd_gguf
  ├ 1) SD3Transformer2DModel.from_single_file(
  │      gguf_path, quantization_config=GGUFQuantizationConfig(fp16))
  │      → transformer만 GGUF 직접 로드
  ├ 2) HF 토큰 자동 탐색 (~\.cache\huggingface\token)
  │      → 게이트 레포 접근용
  └ 3) StableDiffusion3Pipeline.from_pretrained(
         "stabilityai/stable-diffusion-3.5-large",
         transformer=위_트랜스포머,
         text_encoder_3=None, tokenizer_3=None)   ← T5-XXL 제외(메모리 절약)
         → CLIP 2개 + VAE는 stabilityai 레포에서 로드
         → pipe.to("cuda")

[생성 시]
장당 약 31초 (8 steps, guidance_scale=0.0, 1024×576, fp16)
```

---

## 3. 해결한 문제 4가지 (원인 → 해결)

### 3-1. 🔴 모자이크 이미지 — `qk_norm=None` 패치가 원인
- **증상**: 생성은 되는데 이미지 전체가 모자이크/노이즈 덩어리
- **원인**: VRAM 절약 목적으로 `config.json`에서 `qk_norm`을 `None`으로 지우고 로드했음.
  SD 3.5는 **QK-norm(RMSNorm on Q/K projection)이 아키텍처 필수**라 제거하면
  어텐션 스케일이 폭주 → 학습된 가중치와 전혀 안 맞아 모자이크 발생
- **해결**: 원본 `config.json` 그대로 사용 (`qk_norm: "rms_norm"` 유지)

### 3-2. 🔴 `pos_embed` 형상 불일치
- **증상**: 로드 시 shape mismatch 에러 (`[36864,2432]` vs `[1,36864,2432]`)
- **원인**: GGUF 저장 시 배치 차원이 잘려 있고, diffusers 매핑이 이를 보정하지 않음
- **해결**: `gguf_patch.py`에서 `pos_embed` 텐서에 `unsqueeze(0)` 적용

### 3-3. 🔴 QK-norm 가중치가 양자화 raw 상태로 로드됨 (핵심 난제)
- **증상**: 추론 에러 `tensor a(64) vs b(36)` — `norm_q/norm_k` 크기가 (36,)로 로드됨
- **원인**: 이 GGUF는 **QK-norm(ln_q/ln_k)까지 Q4_0으로 양자화**되어 있어
  raw 상태가 `(36,) uint8` 압축 블록.
  diffusers GGUF 로더는 **Linear 레이어만 디퀀타이즈**하므로
  norm 모듈 소속 텐서는 양자화 raw(`GGUFParameter`) 채로 모델에 들어감
- **해결**: `scripts/gguf_patch.py`에서 키에 `ln_q`/`ln_k`가 포함된 `GGUFParameter`를
  `dequantize_gguf_tensor(v).float()`로 수동 변환 → 정상 `(64,)` 평문 텐서
  (총 **152개 텐서** 변환 확인, GGUF 파라미터 529개는 전부 Linear 소속 유지)
- **교훈**: "GGUF에서 QK-norm 크기가 (36,)으로 나오면 모자이크/에러, (64,)이면 정상"

### 3-4. 🟡 폐기한 시도들
| 시도 | 결과 |
|---|---|
| `config.json`에서 `qk_norm=None` 삭제 | 모자이크 유발 (3-1) — 폐기 |
| GGUF→safetensors/.pt 전체 변환 (8.85GB) | VRAM 부담↑, 비양자화 캐스팅 문제 — **폐기, 파일 삭제**. GGUF 직로드 채택 |
| `SD3Transformer2DModel.from_config(폴더)` | deprecated + config dict 구조 문제 — `from_single_file`로 대체 |
| `pipe.enable_vae_tiling()` | SD3 파이프라인에 메서드 없음(로그 확인) — try/except로 무시 |

---

## 4. 핵심 코드 위치

| 파일 | 역할 |
|---|---|
| `scripts/gguf_patch.py` | `apply()` 1회 호출로 diffusers GGUF 로더 몽키패치 (QK-norm 디퀀타이즈 + pos_embed 배치차원) |
| `modules/image_gen.py` `_load_sd_gguf()` | 패치 적용 → GGUF transformer 로드 → 파이프라인 조립(T5 제외) → cuda 이동 |
| `config.py` | `SD_GGUF_CHECKPOINT`(GGUF 경로), `SD_DEVICE="cuda"`, `SD_STEPS=8` |
| `main.py` | 이미지 생성 단계에서 로컬 SD 옵션 선택 시 `_load_sd_gguf` 자동 분기 |

---

## 5. 참고: GGUF 키 → diffusers 매핑

| GGUF 키 | diffusers 키 |
|---|---|
| `model.diffusion_model.joint_blocks.N.x_block...` | `transformer_blocks.N....` |
| `joint_blocks.N.context_block...` | `transformer_blocks.N.context_...` |
| `...attn.ln_q / attn.ln_k` | `...attn.norm_q / attn.norm_k` (QK-norm) |
| `model.diffusion_model.final_layer...` | `proj_out` / `norm_out` |
| `model.diffusion_model.x_embedder` | `pos_embed` |

---

## 6. 실측 성능 (qk_log.txt, 2026-09-16)

```
Transformer 로드: 12.1s (from_single_file + GGUF Q4)
생성: 31.3s (8 steps, 1024×576)
VRAM peak: 7.78GB / 11GB  ← 여유 약 3GB
출력: output/images/turbo_test.png → 모자이크 없음 확인 (사용자 육안)
```

---

## 7. 운영 주의사항

1. **HF 토큰 필수**: CLIP/VAE를 받아오는 `stabilityai/stable-diffusion-3.5-large`는 게이트 레포.
   토큰이 없으면 transformer만 로드되고 파이프라인 조립 실패. (토큰은 `~\.cache\huggingface\token`에서 자동 탐색)
2. **guidance_scale=0.0, steps=8 고정**: Turbo 모델 필수 조건. 바꾸면 화질 붕괴.
3. **첫 로드 12~15초 + 파이프라인 조립 수 초**: 프로세스당 1회, 이후 캐시됨.
4. **GGUF 파일 경로 변경 시**: `config.py`의 `SD_GGUF_CHECKPOINT`만 수정하면 됨.
   다른 GGUF(Q8 등)로 바꿀 때도 `gguf_patch.py`가 그대로 동작함(QK-norm 양자화 여부 자동 판별).
5. **롤백**: `gguf_patch.py`의 `apply()` 호출 라인 제거 + `qk_norm=None` 패치는 절대 복구하지 말 것.

---

## 8. 검증 이력

| 일자 | 내용 | 결과 |
|---|---|---|
| 2026-09-16 | QK-norm (64,) 평문 로드 진단 (`scripts/diag_gguf_params.py`) | ✅ 529개 GGUF 파라미터 전부 Linear, Non-Linear 0개 |
| 2026-09-16 | 패치 후 전체 파이프라인 테스트 (`scripts/test_qknorm_fix.py`) | ✅ 로드 12.1s + 생성 31.3s, `turbo_test.png` |
| 2026-09-16 | 실제 모듈 경로 스모크 테스트 (`main.py`와 동일 경로) | ✅ `scene_99.png` |
| 2026-09-16 | **사용자 육안 확인** | ✅ 모자이크 없음 — 실전 배치 확정 |
