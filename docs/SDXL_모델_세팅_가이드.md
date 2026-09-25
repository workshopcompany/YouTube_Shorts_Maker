# 🖼️ SDXL-Turbo 로컬 이미지 생성 세팅 가이드

**최종 확인**: 2026-09-12 / 이 PC(<project>) 실측 기준
> GPU·torch·CUDA 환경 자체는 [GPU_세팅_가이드.md](GPU_세팅_가이드.md) 참고
> (torch 2.5.1+cu118 고정, 최신 torch 업그레이드 금지 등)

---

## 1. 모델 개요

| 항목 | 내용 |
|---|---|
| 모델 | **SDXL-Turbo** (`stabilityai/sdxl-turbo`) |
| 특징 | Adversarial Diffusion Distillation — **1~4 스텝 즉시 생성**, `guidance_scale=0` |
| 생성 크기 | 512x1024 (세로 1:2 — 쇼츠용, 편집 시 리사이즈) |
| 용량 | 약 13.2GB (diffusers 폴더 레이아웃, 35파일) |
| 라이선스 | StabilityAI 비상업 연구용 (개인 테스트 OK) |
| 선정 이유 | **GTX 1080Ti(11GB, Pascal)에서 수십 초/장 실측 검증된 유일한 로컬 모델** |

> SD 3.5 Large는 8B급이라 11GB VRAM에 미달 → 크래시/오프로드 필요 (9절 참고)

---

## 2. 모델 폴더 현황 (`<project>\model\`)

```
model\
├── sdxl-turbo\                    # ✅ 사용 중 (diffusers 레이아웃)
│   ├── model_index.json
│   ├── unet\  vae\  vae_decoder\  vae_encoder\
│   ├── text_encoder\  text_encoder_2\
│   ├── tokenizer\  tokenizer_2\  scheduler\
│   └── .cache\                    # HF 메타데이터 (삭제 금지)
└── sd3.5_large-q4_k_4_0.gguf      # 📦 보관만 (4.76GB, diffusers 미호환)
```

- SD3.5 Large 원본(15.3GB)·FP8(13.9GB)은 테스트 실패 후 삭제됨 (VRAM 초과)
- **재다운로드가 필요하면 3절 스크립트 사용**

---

## 3. 다운로드 스크립트 (재설치 시에만)

| 스크립트 | 대상 | 상태 |
|---|---|---|
| `scripts\download_sdxl.py` | sdxl-turbo → `model\sdxl-turbo\` | ✅ 완료 |
| `scripts\download_q4.py` | SD3.5 Q4 GGUF → `model\` | 📦 보관만 |
| `scripts\download_fp8.py` | SD3.5 FP8 → `model\` | ❌ 미사용 (삭제됨) |

- 모두 `snapshot_download` 기반: **이어받기(resume) 지원**, lock 파일 자동 정리
- 실행: `.\venv\Scripts\python.exe -X utf8 scripts\download_sdxl.py`
- 참고: SDXL-Turbo는 **HF 로그인 불필요**(공개 저장소)

---

## 4. 코드 연결 설정 (이미 반영됨)

**config.py**
```python
SD_LOCAL_CHECKPOINT = r"<project>\model\sdxl-turbo"
```

**modules/image_gen.py** — SDXL 로딩 옵션 (1080Ti 최적화):
```python
AutoPipelineForText2Image.from_pretrained(
    경로, torch_dtype=torch.float16, variant="fp16", local_files_only=True)
pipe.to("cuda")            # 직접 로드 (SDXL은 오프로드보다 안정·빠름)
pipe.enable_vae_tiling()   # VAE 메모리 절약
```

**생성 파라미터**: `512x1024`, `num_inference_steps=4`, `guidance_scale=0.0`
(Turbo는 낮은 스텝 설계 — 스텝을 늘리면 오히려 품질 저하/과포화 발생)

**SD3.5 분기** (같은 파일에 준비 완료, 미테스트):
- 576x1024, `steps=SD_STEPS(28)`, `enable_model_cpu_offload()`, fp16
- bf16 미지원(1080Ti)이라 fp16 강제

---

## 5. 사용 방법

### 1) 파이프라인에서 실행
```
python main.py → (시작 방식 선택) → 이미지 생성 방식: 1 (로컬 SD)
→ 로컬 SD 경로: 엔터 (기본값 SDXL-Turbo)
```

### 2) 특정 장면만 재생성 (부분 재시도)
```
.\venv\Scripts\python.exe -X utf8 scripts\regen_images.py sd_local 1 5
#                                        방식          ↑장면 범위 (1~5번)
```
- 대본은 `output\script.txt`에서 자동 복구
- 방식: `sd_local` / `gemini` / `placeholder`

### 3) 단독 동작 확인 (모델 테스트)
```
.\venv\Scripts\python.exe -X utf8 test_sdxl_turbo.py
```

---

## 6. 실측 성능 (GTX 1080Ti)

| 단계 | 시간 |
|---|---|
| 파이프라인 로드 | 약 5초 |
| 디노이징 4스텝 | 약 1.4초 (2.8 it/s) |
| **장당 총 소요** | **약 43초** (로드+VAE 디코딩+저장) |
| 12장 전체 | 약 9분 |
| VRAM | fp16 기준 9~10GB (11GB 안전권) |

> 최초 로드 시 `Siglip2ImageProcessorFast` 경고가 나오지만 **무해**

---

## 7. 한글 프롬프트 → 영어 번역 (자동)

대본의 한글 장면 묘사를 영어 프롬프트로 자동 번역해 SD에 전달:

| 순서 | 백엔드 | 비고 |
|---|---|---|
| 1 | **Groq** `openai/gpt-oss-120b` | `reasoning_effort=low` 필수 (reasoning이 max_tokens 먹는 문제 대응) — 검증됨 |
| 2 | **OpenRouter** | `:free` 모델 **실시간 조회** 후 시도 (404 슬러그·빈 응답 라우터 대응) — 검증됨 |
| 3 | Gemini | 폴백 |
| 4 | 멈춰서 선택 | 위 모두 실패 시 메뉴 표시 |

- 번역 캐시: `output\prompt_cache.json` (장면 묘사별 재사용 → API 절약)
- 캐시 초기화: 파일 삭제하면 됨

---

## 8. 알려진 품질 이슈

| 이슈 | 원인 | 대응 |
|---|---|---|
| **이미지 하단에 다른 그림 조각(스트립)이 붙음** | SDXL-Turbo 저스텝 특성상 콜라주형 아티팩트 | ① 해당 장면만 Gemini 재생성: `scripts\regen_images.py gemini N` ② SD3.5 파이프라인 테스트 (9절) |
| 이미지가 약간 흐릿함 | 512x1024 생성 → 편집 시 1080x1920 확대 | SD3.5(576x1024) 테스트 또는 Gemini(1024px급) 사용 |
| 한글 글자 생성 불가 | SD 계열 공통 한계 | 텍스트는 편집 단계(캡컷 등)에서 추가 |

---

## 9. 다음 테스트 예정: SD 3.5 Large

- **목표**: 아티팩트·선명도 개선 (Turbo 대비 품질 상승 기대)
- **준비 상태**: image_gen.py에 SD3.5 분기(오프로드+fp16+28스텝) 구현 완료
- **필요 조치**: SD3.5 Large 재다운로드 (15.3GB — D: 여유 공간 확인)
  → `scripts\download_fp8.py` 대신 **원본 diffusers 버전** 다운로드 스크립트 작성 필요
- **예상**: 장당 수 분 (28스텝 + CPU 오프로드) — Turbo 대비 크게 느림
- **판정 기준**: ① 아티팩트 유무 ② 장당 시간 ③ VRAM 안정성

---

## 10. 관련 문서

- [GPU_세팅_가이드.md](GPU_세팅_가이드.md) — torch 고정, 드라이버, venv 규칙
- [사용법_설명서.md](사용법_설명서.md) — 전체 사용법
- [프로젝트_진행_내역.md](프로젝트_진행_내역.md) — 진행 이력
