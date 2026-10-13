# 🎬 YouTube Shorts Studio

> **아이디어 한 줄 입력 → 대본 · 이미지 · 말풍선 · 나레이션 · MP4 완성 → (선택) 유튜브 업로드**
> Windows 10/11 · 웹 브라우저 편집기 · 무료 API 우선 · **그래픽카드 없이도 사용 가능**

<sub>English: One-stop YouTube Shorts production studio for Windows — Gemini script → images (local SD **or your own pictures**) → comic speech bubbles → Edge-TTS narration → FFmpeg 1080×1920 MP4 → optional YouTube upload. **Only AI image generation needs an NVIDIA GPU; everything else runs on CPU.**</sub>

---

## ✨ 주요 기능

| # | 기능 | 설명 |
|---|---|---|
| 1 | **AI 대본·제목·설명** | 아이디어 한 줄 → 제목 5개 + 설명 + 장면별 대본 (Gemini → OpenRouter → Groq 자동 폴백) |
| 2 | **이미지 3가지 방식** | ① 로컬 SD 자동 생성 ② **직접 업로드(내 이미지)** ③ 건너뛰기(기존 유지) |
| 3 | **대사 말풍선·자막** | 대본 대사를 만화 말풍선 + 하단 자막으로 이미지에 합성 (PIL, 이미지 재생성 없이 글씨만 다시 그리기) |
| 4 | **나레이션 (무료 TTS)** | Edge TTS(기본) / gTTS 폴백, 1.3배속 기본, 문장 사이 무음 자동 정리 |
| 5 | **영상 합성** | 이미지+음성 자동 길이 맞춤 → 1080×1920 MP4 (NVENC GPU 가속, 없으면 CPU 자동 폴백) |
| 6 | **이미지 삽입(합성)** | 기존 이미지 위에 캡처·사진을 원하는 위치·크기로 "박아 넣기" (액자/TV/둥근사각형 프레임) |
| 7 | **대본 직접 수정 모드** | `script.txt` 만 고치면 바뀐 장면만 다시 제작 (API 호출 없이) |
| 8 | **🌐 웹 편집기** | 브라우저에서 3탭으로 대본·이미지·대사·음성·영상 편집 + 변경분만 제작 + 진행 로그 |

**실측 성능** (NVIDIA GTX 1080 Ti 11GB, 12장면 기준): 대본 생성 10초 · 이미지 장당 31초(SD3.5 GGUF Q4, 8 steps) · 영상 33초 MP4 완성

---

## 🖥 그래픽카드 없어도 됩니다 (무GPU 모드)

> **GPU가 필요한 단계는 딱 하나 — "이미지 자동 생성"뿐입니다. 그마저 "내 이미지 올리기"로 우회할 수 있습니다.**

| 단계 | 기능 | GPU 필요? | 사용 방법 |
|---|---|---|---|
| ① | 대본 · 제목 · 설명 생성 | ❌ | 1탭 **"AI로 대본 새로 만들기"** (무료 Gemini 키) |
| ② | 이미지 — 내 사진 사용 | ❌ | 2탭 **"다른 이미지 올리기 → 원본 등록"** |
| ② | 이미지 — 건너뛰기 | ❌ | 3탭 **"건너뛰기"** (기존 이미지 유지) |
| ③ | 대사 말풍선 · 자막 | ❌ | 2탭 **"대사 붙여넣기"** |
| ④ | 나레이션 | ❌ | 2탭 **"전체 음성 다시 만들기"** |
| ⑤ | 영상 합성 | ❌ | 3탭 **"영상 만들기"** (CPU libx264 자동 폴백) |
| ⑥ | 유튜브 업로드 | ❌ | 3탭 업로드 (선택 기능) |
| ②' | **이미지 자동 생성** | ✅ NVIDIA | SDXL-Turbo(8GB+) / SD3.5 GGUF(11GB+) |

- **공식 지원(자동 이미지 생성)**: Windows 10/11 + **NVIDIA 8GB VRAM 이상** (GTX 1080 Ti 포함)
- **AMD / 인텔 내장 / macOS**: 위 표의 "직접 업로드" 경로로 **완전히 동일하게** 영상 제작 가능
- `install.bat` 이 GPU·VRAM을 자동 감지해 모델을 알아서 고릅니다 (`scripts/check_gpu.py`)

---

## ✅ 요구사항

| 항목 | 필수 여부 | 비고 |
|---|---|---|
| Windows 10 / 11 | 필수 | macOS·Linux 미검증 |
| **Python 3.10 ~ 3.11** | 필수 | 3.12+ 는 torch 2.5.1+cu118 휠이 없어 미지원 |
| FFmpeg | 필수 | `install.bat` 이 자동 다운로드 (약 183MB, `ffmpeg8\`) |
| 디스크 여유 | 필수 | 코드 1MB + torch 약 2.5GB + 모델 4.8~13GB |
| **Gemini API 키** | 필수(대본) | 무료 · 발급 1분 |
| Groq / OpenRouter 키 | 선택 | 텍스트 폴백 + 한글→영어 프롬프트 번역 |
| NVIDIA GPU 8GB+ | 선택 | 이미지 자동 생성 시에만 |
| HF 토큰 | 선택 | SD3.5 GGUF 사용 시 (게이트 레포) |
| YouTube OAuth | 선택 | 업로드 기능 사용 시에만 |

---

## 🚀 설치 (3단계 · 약 20~40분, 대부분 다운로드 대기)

```bat
:: 1) 저장소를 받은 폴더에서 install.bat 더블클릭
install.bat        :: Python 확인 → venv → torch(2.5GB) → requirements → FFmpeg → GPU 감지 → 모델 선택

:: 2) .env 파일을 열어 무료 키 입력 (메모장으로 열면 됩니다)
GEMINI_API_KEY=여기에_본인_키      :: https://aistudio.google.com 에서 1분 발급

:: 3) 실행
start_web.bat      :: 브라우저 웹 편집기 자동 실행 (권장)
main.py            :: 터미널(CLI) 방식으로 실행
```

- `install.bat` 은 **이미 설치된 것은 건너뜁니다**(venv·torch 재설치 안 함). 중간에 실패하면 다시 실행하세요.
- 모델 다운로드는 설치 중 `Y` 를 누르거나, 나중에 `python scripts\check_gpu.py --download` 로 받을 수 있습니다.
- 설치 후 문제가 있으면 **`doctor.bat` 더블클릭** → `doctor_report.txt` 생성 → 이슈에 첨부하세요.

### 🔑 API 키 발급 (전부 무료)

| 키 | 발급 | 용도 |
|---|---|---|
| **GEMINI_API_KEY** | [Google AI Studio](https://aistudio.google.com/apikey) | 대본·제목·설명 (필수) |
| GROQ_API_KEY | [Groq Console](https://console.groq.com/keys) | 텍스트 폴백 · 프롬프트 번역 (선택) |
| OpenRouter (`OUTROUTER_API_KEY`) | [OpenRouter Keys](https://openrouter.ai/keys) | 텍스트 폴백 (선택) |
| NVIDIA_API_KEY | [NVIDIA NGC](https://build.nvidia.com/) | 대체 이미지 API (선택) |
| HF_TOKEN | [Hugging Face Token](https://huggingface.co/settings/tokens) | SD3.5 GGUF(게이트 레포) 사용 시 |

> 키는 `.env` 에만 저장하세요. **절대 커밋되지 않습니다** (`.gitignore` 포함).

---

## 🎬 사용 흐름

**웹 편집기 (권장)** — `start_web.bat`

| 탭 | 하는 일 |
|---|---|
| **① 대본** | 아이디어 입력 → "AI로 대본 새로 만들기" / 제목·설명 선택 / 대본 직접 수정 |
| **② 이미지** | 장면별 미리보기 · 다른 이미지 올리기 · 대사(말풍선) 붙여넣기 · 이미지 삽입(박아 넣기) · **목소리 선택(여성 기본 · 남성 변경 가능)** · 음성 다시 만들기 |
| **③ 영상** | 배속·자막 옵션 확인 → "영상 만들기" → 진행 로그 → `output\videos\*.mp4` 저장 · (선택) 유튜브 업로드 |

- 각 단계는 `output\` 에 체크포인트를 남겨서 **중간에 꺼도 이어하기**가 됩니다.
- "대본만 고쳐서 제작" 모드에서는 **바뀐 장면만** 다시 만들어 API·시간을 절약합니다.

---

## 📤 유튜브 업로드 (선택 기능)

1. [Google Cloud Console](https://console.cloud.google.com/) → 프로젝트 생성
2. **YouTube Data API v3** 사용 설정
3. OAuth 동의 화면 구성 → 앱 유형 **데스크톱 앱** → JSON 다운로드 → `client_secret.json` 으로 저장 후 프로젝트 폴더에 배치
4. 웹 편집기 3탭에서 업로드 → 브라우저 로그인 1회 → 이후 자동 (`token.pickle`)

자세한 절차는 **[docs/Google_OAuth_세팅_가이드.md](docs/Google_OAuth_세팅_가이드.md)** 참고.

> ⚠️ **알아두면 좋은 제약**
> - **OAuth 테스트 모드 : refresh 토큰이 7일마다 만료** → 주 1회 재로그인 (앱을 "게시"하면 해소)
> - **업로드 쿼터 : 하루 10,000 units ÷ 업로드 1건 1,600 units = 최대 6개/일**
> - **미검증 앱은 업로드 영상이 비공개로 잠길 수 있음** → 스튜디오에서 직접 공개 전환
> - 상태 확인 : `python check_token.py`

---

## 🛠 문제 해결

**가장 먼저 : `doctor.bat` 실행 → `doctor_report.txt` 를 이슈에 첨부**
(GPU·torch·FFmpeg·모델·키·토큰·디스크·포트를 한 번에 점검합니다. 비밀값은 출력되지 않습니다.)

| 증상 | 원인 | 해결 |
|---|---|---|
| `Python 3.10 or 3.11 was not found` | 파이썬 미설치/버전 불일치 | `winget install Python.Python.3.11` |
| torch 설치 실패 / CUDA 미인식 | 그래픽카드 없음·드라이버 미설치 | 무GPU 모드로 사용 (이미지 직접 업로드) — 나머지 기능은 정상 |
| `ffmpeg 를 찾을 수 없습니다` | FFmpeg 미다운로드 | `python scripts\download_ffmpeg.py` 또는 `winget install FFmpeg` |
| NVENC(가속) 실패 로그 | 드라이버가 FFmpeg 요구 버전보다 낮음 | **정상 동작** — 자동으로 CPU(libx264)로 인코딩, 품질 동일·속도만 느림 |
| 대본 생성 실패 / 429 | 무료 쿼터 초과 | 잠시 후 재시도 · Groq 키 추가(폴백) · 다른 모델 선택 |
| SD3.5 모델 로드 실패 | 게이트 레포 접근 토큰 없음 | `HF_TOKEN` 입력 + [모델 라이선스 동의](https://huggingface.co/stabilityai/stable-diffusion-3.5-large) 후 `check_gpu.py --download` |
| 음성 생성 실패 / 403 오류 | edge-tts 구버전(7.2 이하)이 MS 서버에서 거부됨 | `venv\Scripts\python.exe -m pip install -U edge-tts` (**7.3.1 이상 필요**) |
| 업로드 403 / 로그인 반복 | 토큰 만료(테스트 모드 7일) | `python check_token.py` 확인 → 재로그인 1회 |
| 웹 편집기가 안 열림 | 포트 8765 사용 중 | 다른 프로그램 종료 또는 `set WEBAPP_PORT=8899` 후 실행 |
| 한글 말풍선이 네모로 보임 | 폰트 없음 | Windows 기본 폰트(맑은 고딕) 사용 — Windows 환경 권장 |

---

## ⚠️ 사용 시 주의 (YouTube 정책)

- 생성된 영상은 **반드시 사람이 확인한 뒤 업로드**하세요. 자동 업로드는 편의 기능이며 최종 책임은 사용자에게 있습니다.
- **AI 생성 콘텐츠 공개 의무** : 실제와 구별하기 어려운 AI 콘텐츠는 업로드 시 공개 설정이 필요합니다.
- **반복·대량 생산 콘텐츠** 는 YouTube 수익화 정책에서 제한될 수 있습니다. (같은 틀·같은 대본 반복 등)
- 업로드 쿼터(하루 6개)와 테스트 모드 토큰 만료(7일)는 Google 정책이며 이 프로그램이 바꿀 수 없습니다.

---

## 📁 프로젝트 구조

```
youtube-shorts-studio/
├── install.bat            # 1회 설치 (venv·torch·FFmpeg·모델·.env)
├── start_web.bat          # 웹 편집기 실행 (권장)
├── doctor.bat             # 환경 진단 → doctor_report.txt
├── main.py                # 터미널(CLI) 실행
├── webapp.py              # 웹 편집기 서버 (기본 포트 8765)
├── config.py              # 설정 (.env 에서 키 로드, 절대경로 없음)
├── .env.example           # 키 템플릿 (복사해서 .env 로)
├── requirements.txt
├── modules/               # text_gen · image_gen · script_store · overlay · pipeline · tts · video_edit · youtube_upload
├── scripts/               # check_gpu · doctor · download_ffmpeg · download_sdxl · gguf_patch · web_job · verify_*
├── webui/index.html       # 웹 편집기 화면 (3탭)
├── test/                  # 회귀 테스트 (모델·API 없이 실행 가능)
├── docs/                  # 세팅 가이드 (OAuth · GPU · SDXL · SD3.5 · OpenRouter)
├── output/                # 생성물 (script.txt / images / audio / videos) — git 제외
├── model/                 # 로컬 모델 — git 제외, 설치 시 다운로드
└── ffmpeg8/               # FFmpeg — git 제외, 설치 시 다운로드
```

> 코드를 수정하기 전에는 **[ARCHITECTURE.md](ARCHITECTURE.md)**(데이터 흐름·수정 매트릭스·불변 규칙)를 먼저 확인하세요.

---

## 🧪 테스트

```bat
:: 1) 문법 검사 (언제나 안전)
venv\Scripts\python.exe -m py_compile webapp.py config.py modules\pipeline.py

:: 2) 설치 직후에도 통과하는 테스트 5종 (모델·API 키·output 자료 불필요 · 실측 통과)
venv\Scripts\python.exe test\test_script_only_flow.py
venv\Scripts\python.exe test\test_script_sync.py
venv\Scripts\python.exe test\test_text_web.py
venv\Scripts\python.exe test\test_webapp.py
venv\Scripts\python.exe test\test_web_tts.py

:: 3) 전체 실행
for %f in (test\test_*.py) do venv\Scripts\python.exe %f
```

- 위 2번 5종은 **깨끗한 새 클론에서도 통과**합니다(내부 임시 폴더 사용).
- 나머지 테스트는 `output\` 작업물(대본·이미지·음성)·로컬 모델·API 키가 준비된 상태를 전제로 하므로
  **영상을 한 번 만든 뒤** 실행하세요. (2026-09-25 실측: 원본 개발 트리에서도 동일하게 실패 → 환경 의존 테스트)
- 테스트는 대부분 `SAAS_OUTPUT_DIR` 격리 모드를 사용해 실제 `output\` 을 덮어쓰지 않습니다.

---

## 📚 문서

| 문서 | 내용 |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 시스템 지도 · 수정 위치 · 불변 규칙 (개발자 필독) |
| [사용법_설명서.md](사용법_설명서.md) | 전체 사용법 · 메뉴별 설명 · 문제 해결 |
| [docs/Google_OAuth_세팅_가이드.md](docs/Google_OAuth_세팅_가이드.md) | 유튜브 업로드 OAuth 세팅 |
| [docs/GPU_세팅_가이드.md](docs/GPU_세팅_가이드.md) | torch/CUDA 버전 고정 이유 |
| [docs/SD3.5_Large_Turbo_설정보고서.md](docs/SD3.5_Large_Turbo_설정보고서.md) | 로컬 이미지 생성 문제 해결 기록 |
| [docs/SDXL_모델_세팅_가이드.md](docs/SDXL_모델_세팅_가이드.md) | SDXL-Turbo 모델 준비 |
| [docs/OpenRouter_API_세팅법.md](docs/OpenRouter_API_세팅법.md) | 텍스트 폴백 API 설정 |

---

## 📄 라이선스

- 이 저장소의 **자체 코드** : [MIT License](LICENSE)
- **모델·FFmpeg은 저장소에 포함되지 않습니다** (설치 시 사용자 PC로 다운로드) → [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- SDXL / SD 3.5 가중치는 **Stability AI Community License** 를 따르며 MIT 적용 대상이 아닙니다.


