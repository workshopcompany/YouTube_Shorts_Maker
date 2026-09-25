# 서드파티 고지 / Third-Party Notices

이 저장소는 **자체 코드만** 포함합니다. 아래 항목은 저장소에 포함하지 않으며
사용자 PC에서 설치·다운로드됩니다.

| 항목 | 라이선스 | 배포 방식 |
|---|---|---|
| **FFmpeg** (BtbN win64-gpl 빌드) | GPL v3 (빌드 옵션에 따라 LGPL) | ❌ 미포함 — `install.bat` → `scripts/download_ffmpeg.py` 가 사용자 PC로 다운로드 |
| **SDXL-Turbo** (`stabilityai/sdxl-turbo`) | Stability AI Community License | ❌ 미포함 — `scripts/download_sdxl.py` 로 사용자 PC 다운로드 |
| **SD 3.5 Large / Turbo** (`stabilityai/stable-diffusion-3.5-*`) | Stability AI Community License | ❌ 미포함 — 사용자 PC 다운로드 (게이트 레포, HF 토큰 필요) |
| **SD3.5 Turbo GGUF 양자화** (`city96/stable-diffusion-3.5-large-turbo-GGUF`) | 원본 모델 라이선스 승계 (Stability AI Community License) | ❌ 미포함 — `python scripts/check_gpu.py --download` |
| **PyTorch / torchvision / torchaudio** | BSD-3-Clause | pip 설치 (사용자 PC) |
| **diffusers / transformers / huggingface_hub** | Apache-2.0 | pip 설치 |
| **MoviePy** | MIT | pip 설치 |
| **Pillow** | HPND (PIL License) | pip 설치 |
| **edge-tts** | GPL-3.0 (별도 프로세스·pip 설치, 코드 미포함) | pip 설치 |
| **gTTS** | MIT | pip 설치 |
| **google-api-python-client / google-auth / google-generativeai** | Apache-2.0 | pip 설치 |
| **groq / openai / requests / python-dotenv / tqdm / colorama / pydub** | MIT / Apache-2.0 / BSD | pip 설치 |

## 주의 (재배포 시)

1. FFmpeg GPL 빌드를 **저장소에 함께 올리면** GPL 의무(소스 제공 등)가 발생합니다.
   이 저장소는 동봉하지 않고 설치 시 다운로드합니다.
2. 모델 가중치(SDXL / SD 3.5)는 각 라이선스(Stability AI Community License)를 따르며,
   **이 저장소의 MIT 라이선스가 모델에 적용되지 않습니다.**
3. YouTube Data API 사용 시 Google API 서비스 약관 및 YouTube 정책을 준수해야 합니다.
   (AI 생성 콘텐츠 공개 의무, 반복·대량 생산 콘텐츠 수익화 제한 등)
