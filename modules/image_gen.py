"""
YouTube 자동화 - 이미지 생성 모듈
Gemini/NVIDIA API를 사용하여 쇼츠 이미지 생성
"""

import os
import json
import hashlib
import base64
import time
import requests
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
from config import GEMINI_API_KEY, NVIDIA_API_KEY, OUTPUT_DIR, IMAGE_STYLE, GEMINI_IMAGE_MODEL, SD_LOCAL_CHECKPOINT, SD_GGUF_CHECKPOINT, SD_DEVICE, SD_STEPS, OUTROUTER_API_KEY, GROQ_API_KEY, CHARACTER_PROMPT_EN, SPEECH_BUBBLE, BUBBLE_FONT_SIZE

# 텍스트(말풍선/자막) 합성 모듈 — base 원본 보관 + API 재호출 없이 텍스트만 다시 그리기
try:
    from modules import overlay as overlay_mod
except ImportError:  # modules 폴더가 sys.path 에 직접 잡힌 경우
    import overlay as overlay_mod


class ImageGenerator:
    """이미지 생성 3옵션: 1) 로컬 SD 3.5 Large / 2) Gemini 실전용 / 3) 플레이스홀더"""

    def __init__(self, mode="gemini", local_model_path=None, use_nvidia=False, use_local=False):
        # 하위호환: 기존 use_nvidia / use_local 플래그를 mode로 변환
        if use_nvidia:
            mode = "gemini"  # NVIDIA 무료 API에 이미지 생성 없음 -> Gemini로 유도
        if use_local:
            mode = "sd_local"
        if mode not in ("sd_local", "gemini", "placeholder"):
            mode = "gemini"
        self.mode = mode
        self.local_model_path = local_model_path
        self.output_dir = Path(OUTPUT_DIR) / "images"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._sd_pipe = None
        self._sd_is_sdxl = False
        self._preferred_backend = None  # 번역 실패 시 사용자가 선택한 백엔드 기억

    # ---------- 1) 로컬 SD (SDXL-Turbo 폴더 / SD 3.5 단일파일 모두 지원) ----------
    def _load_sd_local(self):
        """로컬 SD 파이프라인 로드. 폴더(SDXL-Turbo)=direct cuda, 파일(SD3.5)=기존 방식. 첫 호출 시 1회만."""
        if self._sd_pipe is not None:
            return self._sd_pipe
        try:
            import torch
        except ImportError as e:
            print(f"❌ torch 미설치: {e}")
            return None
        ckpt = self.local_model_path or SD_LOCAL_CHECKPOINT
        if not ckpt or not os.path.exists(str(ckpt)):
            print(f"❌ 로컬 SD 체크포인트 없음: {ckpt}")
            print("   main 메뉴에서 경로를 입력하거나 config.py의 SD_LOCAL_CHECKPOINT를 확인하세요.")
            return None
        # 폴더 방식 (SDXL-Turbo diffusers 폴더) — 1080Ti 검증됨 (43초/장)
        if os.path.isdir(str(ckpt)):
            try:
                from diffusers import AutoPipelineForText2Image
                import torch
                print(f"🔄 SDXL-Turbo 로드 중... ({ckpt})")
                pipe = AutoPipelineForText2Image.from_pretrained(
                    str(ckpt), torch_dtype=torch.float16,
                    variant="fp16", local_files_only=True,
                )
                pipe.to("cuda")  # 1080Ti: cpu_offload 쓰면 VAE 단계에서 크래시 → direct cuda
                try:
                    pipe.enable_vae_tiling()
                except Exception:
                    pass
                self._sd_pipe = pipe
                self._sd_is_sdxl = True
                print("✅ SDXL-Turbo 로드 완료 (direct cuda + vae_tiling)")
                return pipe
            except Exception as e:
                print(f"❌ SDXL 로드 실패: {e}")
                return None
        # 단일파일 방식 (SD 3.5 Large) — GGUF Q4 로컬 모델
        if str(ckpt).lower().endswith(".gguf"):
            return self._load_sd_gguf(ckpt)
        try:
            from diffusers import StableDiffusion3Pipeline
            import torch
            print(f"🔄 SD 3.5 Large 로드 중... ({ckpt})")
            pipe = StableDiffusion3Pipeline.from_single_file(
                str(ckpt), torch_dtype=torch.float16
            )
            if SD_DEVICE == "cuda":
                pipe.to("cuda")
            else:
                pipe.to("cpu")
            try:
                pipe.enable_vae_tiling()
            except Exception:
                pass
            self._sd_pipe = pipe
            print("✅ SD 3.5 Large 로드 완료")
            return pipe
        except Exception as e:
            print(f"❌ SD 로드 실패: {e}")
            return None

    # ---------- 1-0) SD 3.5 Large GGUF 로드 (Q4, 1080Ti 검증) ----------
    def _load_sd_gguf(self, ckpt_path):
        """SD 3.5 Large Q4 GGUF 단일파일 로드: transformer만 GGUF, CLIP+VAE는 HF에서 다운로드.
        config는 원본 config.json 사용 (qk_norm 유지)."""
        if self._sd_pipe is not None:
            return self._sd_pipe
        try:
            import torch, gc, os, sys
        except ImportError as e:
            print(f"❌ import 실패: {e}")
            return None
        from diffusers import SD3Transformer2DModel, StableDiffusion3Pipeline
        from diffusers.quantizers.quantization_config import GGUFQuantizationConfig
        import huggingface_hub as hh

        # --- GGUF 로드 패치 (QK-norm 디퀀타이즈 + pos_embed 배치차원) ---
        _scripts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
        if _scripts_dir not in sys.path:
            sys.path.insert(0, _scripts_dir)
        from gguf_patch import apply as _apply_gguf_patch
        _apply_gguf_patch()

        t0 = time.time() if 'time' in dir() else __import__('time').time()
        ckpt_path = str(ckpt_path)
        print(f"🔄 SD 3.5 Large GGUF 로드 중... ({ckpt_path})")

        # --- HF 토큰 (게이트 레포용) ---
        token = None
        for _p in (os.path.expanduser(r"~\.cache\huggingface\token"),
                   os.path.expanduser(r"~\.huggingface\token")):
            if os.path.exists(_p):
                token = open(_p, encoding="utf-8").read().strip()
                os.environ["HF_TOKEN"] = token
                break
        if not token:
            print("⚠️ HF 토큰 없음 — CLIP/VAE 다운로드 불가")

        # --- 1) transformer 로드 (GGUF 직접, from_single_file) ---
        import time
        t0 = time.time()
        print("   트랜스포머 로드 (GGUF Q4)...")
        _qcfg = GGUFQuantizationConfig(compute_dtype=torch.float16)
        transformer = SD3Transformer2DModel.from_single_file(
            ckpt_path, quantization_config=_qcfg,
            torch_dtype=torch.float16, token=token, low_cpu_mem_usage=True,
        )
        gc.collect()
        print(f"   ✅ 트랜스포머 완료: {time.time()-t0:.1f}s")

        # --- 3) 파이프라인 조립 (T5 제외, CLIP+VAE만) ---
        pipe = StableDiffusion3Pipeline.from_pretrained(
            "stabilityai/stable-diffusion-3.5-large",
            transformer=transformer, text_encoder_3=None, tokenizer_3=None,
            torch_dtype=torch.float16, token=token,
        )
        if SD_DEVICE == "cuda":
            pipe.to("cuda")
        else:
            pipe.to("cpu")
        try:
            pipe.enable_vae_tiling()
        except Exception:
            pass
        self._sd_pipe = pipe
        print(f"✅ SD 3.5 Large GGUF 로드 완료: {time.time()-t0:.1f}s")
        return pipe

    # ---------- 1-0) SDXL용 프롬프트 준비 (한글→영어 번역, 무료 API + 실패 시 선택) ----------
    @staticmethod
    def _translation_instructions(text: str) -> str:
        """번역 공통 지시문: '해당 장면 묘사만' 영어 프롬프트로."""
        return (
            "Translate this Korean image description into an English "
            "image-generation prompt for Stable Diffusion.\n"
            "- Output ONLY the prompt body: comma-separated short phrases, max 40 words\n"
            "- Describe only what is written in THIS scene: subject, action, "
            "background, lighting, camera angle\n"
            "- No quotes, no explanations, no extra text\n\n"
            f"Korean description: {text.strip()}"
        )

    _OR_EXCLUDE = ("r1", "qwq", "thinking", "reason", "o1", "o3", "o4",
                   "ling", "sante", "laguna", "poolside")  # reasoning 전용/내용 미반환 계열

    def _openrouter_free_models(self, limit: int = 3):
        """OpenRouter에서 현재 살아있는 무료 모델 목록 실시간 조회
        (text_gen.list_groq_models와 동일 패턴). reasoning 계열은 제외."""
        try:
            r = requests.get("https://openrouter.ai/api/v1/models", timeout=30)
            if r.status_code != 200:
                return []
            ids = [m.get("id", "") for m in r.json().get("data", [])]
            free = [i for i in ids if i.endswith(":free") and not any(
                k in i.lower() for k in self._OR_EXCLUDE)]
            # 대화형(번역 가능) 추정 모델 우선 정렬
            free.sort(key=lambda x: 0 if any(
                k in x.lower() for k in ("flash", "instruct", "-it", "chat")) else 1)
            return free[:limit]
        except Exception:
            return []

    def _translate_via_openrouter(self, text: str, attempts: int = 1):
        """OpenRouter 무료 모델로 번역. 모델 목록을 실시간 조회해 살아있는
        무료 모델을 순차 시도(구형 slug 404 방지) + 마지막에 free 라우터.
        성공: 영어 / 실패: None"""
        headers = {
            "Authorization": f"Bearer {OUTROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/youtube-automation-saas",
            "X-Title": "YouTube Automation SaaS",
        }
        models = self._openrouter_free_models() + ["openrouter/free"]
        for model in models:
            for attempt in range(1, attempts + 1):
                try:
                    payload = {
                        "model": model,
                        "messages": [{"role": "user", "content": self._translation_instructions(text)}],
                        "max_tokens": 300,
                    }
                    resp = requests.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers=headers, json=payload, timeout=60,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        msg = (data.get("choices") or [{}])[0].get("message", {})
                        en = (msg.get("content") or "").strip().strip('"').strip()
                        if en:
                            print(f"   ✅ OpenRouter 번역 모델: {model}")
                            return en
                        print(f"⚠️ [{model}] 응답에 내용 없음 — 다음 모델 시도")
                    else:
                        print(f"⚠️ [{model}] 번역 실패 ({attempt}/{attempts}): "
                              f"{resp.status_code} {resp.text[:120]}")
                except Exception as e:
                    print(f"⚠️ [{model}] 번역 오류 ({attempt}/{attempts}): {e}")
        return None

    def _translate_via_groq(self, text: str):
        """Groq 무료 모델(openai/gpt-oss-120b)로 번역.
        gpt-oss는 reasoning 모델 → reasoning_effort=low + 넉넉한 max_tokens 필요
        (기존 text_gen의 extra_payload/reasoning 패턴 참고). 성공: 영어 / 실패: None"""
        try:
            headers = {
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": "openai/gpt-oss-120b",
                "messages": [{"role": "user", "content": self._translation_instructions(text)}],
                "max_tokens": 400,          # 추론 토큰 + 번역 본문 여유
                "reasoning_effort": "low",  # 추론이 출력 한도를 먹지 않게 (gpt-oss 지원)
            }
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers, json=payload, timeout=60,
            )
            if resp.status_code == 400 and "reasoning_effort" in payload:
                # 미지원 모델 → 옵션 제거 후 1회 재시도 (text_gen과 동일 패턴)
                payload.pop("reasoning_effort", None)
                resp = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers, json=payload, timeout=60,
                )
            if resp.status_code == 200:
                msg = (resp.json().get("choices") or [{}])[0].get("message", {})
                en = (msg.get("content") or "").strip().strip('"').strip()
                if not en:
                    # reasoning 본문에 번역이 붙어오는 경우 대비
                    en = (msg.get("reasoning") or "").strip().strip('"').strip()
                if en:
                    return en
                print(f"⚠️ Groq 응답에 내용 없음 — 진단: {resp.text[:200]}")
            else:
                print(f"⚠️ Groq 번역 실패: {resp.status_code} {resp.text[:120]}")
        except Exception as e:
            print(f"⚠️ Groq 번역 오류: {e}")
        return None

    def _translate_via_gemini(self, text: str):
        """Gemini 텍스트 모델로 번역 (토큰 소모 — 최후 수단). 성공: 영어 / 실패: None"""
        try:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-3.5-flash:generateContent?key={GEMINI_API_KEY}"
            )
            resp = requests.post(
                url,
                json={"contents": [{"parts": [{"text": self._translation_instructions(text)}]}]},
                timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json()
                en = data["candidates"][0]["content"]["parts"][0]["text"]
                en = en.strip().strip('"').strip()
                if en:
                    return en
            print(f"⚠️ Gemini 번역 실패: {resp.status_code} {resp.text[:120]}")
        except Exception as e:
            print(f"⚠️ Gemini 번역 오류: {e}")
        return None

    def _cache_get(self, text: str):
        """번역 캐시 조회 (output/prompt_cache.json)"""
        cache_file = Path(OUTPUT_DIR) / "prompt_cache.json"
        if cache_file.exists():
            try:
                cache = json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                return None
            key = hashlib.md5(text.strip().encode("utf-8")).hexdigest()[:10]
            return cache.get(key)
        return None

    def _cache_put(self, text: str, en: str):
        """번역 캐시 저장 (같은 장면 재생성 시 API 호출 절약)"""
        cache_file = Path(OUTPUT_DIR) / "prompt_cache.json"
        cache = {}
        if cache_file.exists():
            try:
                cache = json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                cache = {}
        key = hashlib.md5(text.strip().encode("utf-8")).hexdigest()[:10]
        cache[key] = en
        cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")

    def translate_prompt(self, text: str) -> str:
        """한글 장면 묘사 → 영어 프롬프트.
        순서: 캐시 → 선호 백엔드(사용자가 이전에 선택한 API) → Groq(검증됨, 무료)
        → OpenRouter(무료 모델 실시간 탐색) → 그래도 실패하면 '멈춰서' API 선택."""
        cached = self._cache_get(text)
        if cached:
            return cached

        en, backend = None, None
        if self._preferred_backend:  # 1) 이전에 선택한 백엔드 우선
            backend = self._preferred_backend
            en = getattr(self, f"_translate_via_{backend}")(text)

        if en is None:  # 2) 기본: Groq (무료, 검증됨)
            backend = "groq"
            en = self._translate_via_groq(text)

        if en is None:  # 3) 대안: OpenRouter (무료 모델 자동 탐색)
            backend = "openrouter"
            en = self._translate_via_openrouter(text)

        while en is None:  # 4) 모두 실패 → 멈춰서 선택
            print("\n⏸️ 프롬프트 번역 실패 — 어떻게 할까요?")
            print("   1. Groq 재시도 (무료, 권장)")
            print("   2. OpenRouter 재시도 (무료, 모델 자동 탐색)")
            print("   3. Gemini로 번역 (토큰 소모)")
            print("   4. 번역 건너뛰기 (한글 원문 사용 — 이미지가 내용과 안 맞을 수 있음)")
            c = input("선택 (1/2/3/4): ").strip()
            if c == "1":
                en = self._translate_via_groq(text)
                backend = "groq"
            elif c == "2":
                en = self._translate_via_openrouter(text)
                backend = "openrouter"
            elif c == "3":
                en = self._translate_via_gemini(text)
                backend = "gemini"
            elif c == "4":
                print("   → 번역 없이 진행합니다.")
                return text
            else:
                print("   1~4 중에서 선택하세요.")

        if en is not None and backend in ("groq", "openrouter", "gemini"):
            self._preferred_backend = backend  # 이후 장면도 선택한 API 사용
        self._cache_put(text, en)
        return en

    def _build_sd_prompt(self, prompt: str) -> str:
        """SDXL용 최종 프롬프트: 번역된 내용 맨 앞 + 영어 스타일 + 길이 제한.
        CLIP 인코더는 앞쪽 토큰에 가중치 → '내용 우선' 배치."""
        en_subject = self.translate_prompt(prompt)
        # AI 공개 라벨 회피: 실사가 아니라 명백한 웹툰/만화로 나오도록 스타일 토큰 강화
        # (터보 모델은 guidance_scale=0 → 네거티브 프롬프트 무효, positive에만 명시)
        # 주인공 캐릭터 토큰을 맨 앞에 고정 → 모든 장면에서 동일 캐릭터 일관성 유지
        # "no text": 말풍선 텍스트는 PIL이 직접 그리므로 SD가 글자를 그리지 않게 함
        full = (
            f"{CHARACTER_PROMPT_EN}, 2d korean webtoon illustration, manhwa comic art, "
            "flat cel shading, bold clean outlines, "
            f"{en_subject}, cartoon character design, bright vivid colors, "
            "vertical 9:16 portrait, high quality flat cartoon artwork, no text"
        )
        words = full.split()
        if len(words) > 60:  # CLIP 77토큰 한도 대비 안전 마진
            full = " ".join(words[:60])
        return full

    def generate_with_sd_local(self, prompt: str, scene_num: int) -> str:
        """로컬 SD로 576x1024(9:16) 생성 → Lanczos로 1080x1920 업스케일 저장.
        (SDXL이면 steps=4/guidance=0, SD3.5면 config 스텝. 1080x1920 직접 생성은
        1080Ti VRAM 부족 → 네이티브 9:16 + 고품질 업스케일 방식)

        생성 결과가 단색(회색)이면 시드를 바꿔 1회 재시도하고,
        그래도 실패면 None 을 반환해 **기존 이미지파일을 덮지 않는다**.
        (fp16 오버플로 등으로 '성공' 처리된 빈 이미지가 저장되는 사고 방지)
        """
        pipe = self._load_sd_local()
        if pipe is None:
            return None
        attempts = 2
        for attempt in range(attempts):
            try:
                full_prompt = self._build_sd_prompt(prompt)
                tag = "(재시도)" if attempt else ""
                print(f"   🖼️ SD 프롬프트{tag}: {full_prompt}")
                import torch
                with torch.inference_mode():
                    if getattr(self, "_sd_is_sdxl", False):
                        image = pipe(
                            prompt=full_prompt, height=1024, width=576,
                            num_inference_steps=4, guidance_scale=0.0,
                        ).images[0]
                    else:
                        image = pipe(
                            prompt=full_prompt, height=1024, width=576,
                            num_inference_steps=SD_STEPS, guidance_scale=0.0,
                        ).images[0]
                # 9:16 네이티브(576x1024) → 유튜브 쇼츠 규격(1080x1920)으로 고품질 업스케일
                image = image.resize((1080, 1920), Image.LANCZOS)
                # 생성 실패(단색/저분산) 검증 — 저장 전에 걸러야 기존 이미지가 보존됨
                bad, why = overlay_mod.is_suspect_pil_image(image)
                if bad:
                    if attempt < attempts - 1:
                        print(f"   ⚠ {why} → 시드 바꿔 1회 재시도")
                        continue
                    print(f"   ❌ {why} — 생성 실패로 처리 (기존 이미지 보존)")
                    return None
                img_path = self.output_dir / f"scene_{scene_num:02d}.png"
                image.save(img_path)
                return str(img_path)
            except Exception as e:
                print(f"❌ SD 로컬 생성 실패: {e}")
                return None
        return None

    # ---------- 2) Gemini 실전용 ----------
    def generate_with_gemini(self, prompt: str, scene_num: int) -> str:
        """Gemini 3.1-flash-image (Nano Banana 2)로 실제 이미지 생성"""
        try:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{GEMINI_IMAGE_MODEL}:generateContent?key={GEMINI_API_KEY}"
            )
            full_prompt = f"{IMAGE_STYLE}. {prompt}. 9:16 vertical, YouTube Shorts, no text overlay"
            payload = {
                "contents": [{"parts": [{"text": full_prompt}]}],
                "generationConfig": {"responseModalities": ["IMAGE"]},
            }
            resp = requests.post(url, json=payload, timeout=120)
            if resp.status_code != 200:
                print(f"❌ Gemini 이미지 오류: {resp.status_code} {resp.text[:300]}")
                return None
            data = resp.json()
            for cand in data.get("candidates", []):
                for part in cand.get("content", {}).get("parts", []):
                    b64 = part.get("inlineData", {}).get("data")
                    if b64:
                        img_path = self.output_dir / f"scene_{scene_num:02d}.png"
                        with open(img_path, "wb") as f:
                            f.write(base64.b64decode(b64))
                        return str(img_path)
            print("❌ Gemini 응답에 이미지 없음")
            return None
        except Exception as e:
            print(f"❌ Gemini 이미지 생성 실패: {e}")
            return None

    # ---------- (구) NVIDIA: 무료 API에 이미지 생성 없음 -> Gemini로 유도 ----------
    def generate_with_nvidia(self, prompt: str, scene_num: int) -> str:
        print("⚠️ NVIDIA 무료 API에는 이미지 생성 모델이 없습니다. Gemini로 전환합니다.")
        return self.generate_with_gemini(prompt, scene_num)

    # ---------- 말풍선 (PIL 직접 렌더링) ----------
    @staticmethod
    def _wrap_bubble_text(draw, text: str, font, max_w: int) -> list:
        """말풍선용 줄바꿈 (공백 단위 우선, 긴 단어는 글자 단위 분할)"""
        lines, cur = [], ""
        for word in text.split(" "):
            cand = (cur + " " + word).strip()
            if draw.textlength(cand, font=font) <= max_w:
                cur = cand
                continue
            if cur:
                lines.append(cur)
            # 단어 자체가 최대 폭을 넘으면 글자 단위로 쪼갬
            while draw.textlength(word, font=font) > max_w and len(word) > 1:
                cut = len(word)
                while cut > 1 and draw.textlength(word[:cut], font=font) > max_w:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            cur = word
        if cur:
            lines.append(cur)
        return lines or [text]

    def add_speech_bubble(self, img_path: str, text: str):
        """(호환용) 장면 대사를 말풍선으로 이미지에 합성.

        실제 구현은 modules/overlay.py 로 이동했다(스타일/위치/크기 선택 가능).
        여기서는 기존 동작(흰 말풍선 + 검정 테두리)을 그대로 유지한다.
        """
        if not (text or "").strip():
            return
        try:
            cfg = overlay_mod.load_config()
            cfg = dict(cfg)
            cfg["style"] = "bubble"
            img = Image.open(img_path)
            out = overlay_mod.draw_text(img, text, cfg, legacy=True)
            out.save(img_path)
            print("   💬 말풍선 삽입 완료 (overlay 모듈)")
        except Exception as e:
            print(f"   ⚠ 말풍선 삽입 실패 (원본 이미지 유지): {e}")

    def generate_scene_images(self, script: list, start_index: int = 1) -> list:
        """
        대본의 각 장면에 대한 이미지 생성
        start_index: 이번 배치의 첫 장면 번호(1부터).
                     main.py가 장면을 하나씩 호출하므로 실제 장면 번호를 넘겨야
                     모든 이미지가 scene_01.png에 덮여쓰여지는 버그가 생기지 않음.
        반환: ["이미지경로1", "이미지경로2", ...]
        """
        image_paths = []
        
        total = start_index + len(script) - 1
        for offset, scene in enumerate(script):
            i = start_index + offset
            print(f"🎨 이미지 생성 중... [{i}/{total}]")
            
            visual_desc = scene.get("visual", scene.get("content", ""))

            if self.mode == "sd_local":
                path = self.generate_with_sd_local(visual_desc, i)
                # SD 실패 시 Gemini로 폴백
                if path is None:
                    print("   ⚠️ SD 실패 → Gemini로 폴백")
                    path = self.generate_with_gemini(visual_desc, i)
            elif self.mode == "placeholder":
                tmp = self.create_placeholder_images([scene], start_index=i)
                path = tmp[0] if tmp else None
            else:  # gemini
                path = self.generate_with_gemini(visual_desc, i)
            
            if path:
                # ① 원본(텍스트 없는) 이미지를 base 폴더에 보관
                #    → 대사만 수정했을 때 API/SD 재호출 없이 텍스트만 다시 그릴 수 있음
                # ② 장면 대사를 이미지에 합성 (말풍선/자막 등 overlay_config.json 설정 사용)
                try:
                    overlay_mod.save_base_from(path, i)
                    dialogue = (scene.get("content") or "").strip()
                    cfg = overlay_mod.load_config()
                    if dialogue and cfg.get("style") != "none":
                        overlay_mod.apply_scene(i, text=dialogue, cfg=cfg, mark=False)
                except Exception as e:
                    print(f"   ⚠ 텍스트 합성 실패 (이미지 원본 유지): {e}")
                image_paths.append(path)
                print(f"   ✅ 완료: {path}")
            else:
                print(f"   ⚠️ 실패: 장면 {i}")
        
        return image_paths
    
    def create_placeholder_images(self, script: list, start_index: int = 1) -> list:
        """
        테스트용 플레이스홀더 이미지 생성
        실제 API 없이 테스트 가능
        start_index: 첫 장면 번호 (장면 하나씩 호출할 때 실제 번호 전달용)
        """
        from PIL import Image, ImageDraw, ImageFont
        import textwrap
        
        image_paths = []
        
        for offset, scene in enumerate(script):
            i = start_index + offset
            # 1080x1920 빈 이미지 생성
            img = Image.new('RGB', (1080, 1920), color=(30, 30, 50))
            draw = ImageDraw.Draw(img)
            
            # 장면 번호 표시
            text = f"장면 {i}\n{scene.get('content', '')[:50]}"
            
            # 텍스트 그리기
            try:
                # Windows 한글 폰트 시도
                font = ImageFont.truetype(r"C:\Windows\Fonts\malgun.ttf", 50)
            except:
                try:
                    # 대체 폰트
                    font = ImageFont.truetype(r"C:\Windows\Fonts\gulim.ttc", 50)
                except:
                    font = ImageFont.load_default()
            
            # 텍스트 줄바꿈 처리 (좌우 여백 확보)
            margin = 80  # 좌우 여백
            max_width = 1080 - (margin * 2)  # 최대 텍스트 너비
            
            # 줄바꿈 처리
            lines = []
            for line in text.split('\n'):
                if line:
                    # textwrap으로 줄바꿈
                    wrapped = textwrap.wrap(line, width=20)
                    lines.extend(wrapped)
                else:
                    lines.append('')
            
            # 텍스트 총 높이 계산
            line_height = 60
            total_text_height = len(lines) * line_height
            
            # 하단에 텍스트 배치
            y_start = 1920 - total_text_height - 100  # 하단에서 100px 위
            
            # 각 줄 그리기
            for j, line in enumerate(lines):
                # 텍스트 너비 계산
                bbox = draw.textbbox((0, 0), line, font=font)
                text_width = bbox[2] - bbox[0]
                
                # 중앙 정렬
                x = (1080 - text_width) // 2
                y = y_start + (j * line_height)
                
                draw.text((x, y), line, fill=(255, 255, 255), font=font)
            
            # 저장
            img_path = self.output_dir / f"scene_{i:02d}.png"
            img.save(img_path)
            image_paths.append(str(img_path))
            
            print(f"🎨 플레이스홀더 이미지 생성: {img_path}")
        
        return image_paths


def ensure_scene_images(script: list, log=print) -> tuple:
    """장면별 이미지 경로 목록을 대본 길이와 1:1로 보장한다.

    - 실제 이미지(images/scene_XX.png)가 없는 장면은 `_placeholder/` 아래에
      임시 플레이스홀더를 만들어 자리를 채운다.
      (실제 경로는 건드리지 않아야 이후 웹 UI의 '이미지 없음' 상태가 사라지지 않고
       '이미지 만들기' 재생성이 그대로 유도됨)
    - 반환: (images, missing)
        images : len(script) 와 항상 같은 경로 목록 (영상/자막/음성 인덱스 유지용)
        missing: 실제 이미지가 없었던 장면 번호 리스트 (1-based)
    - 영상 생성 시 exists 필터로 장면이 통째로 빠지는 문제를 막기 위한 안전장치
      (필터를 하면 n번째 자리에 n+1번 이미지가 들어와 장면-음성-자막이 엇갈림)
    """
    from PIL import Image, ImageDraw, ImageFont
    from modules import script_store
    import textwrap

    images, missing = [], []
    ph_dir = script_store.scene_image_path(1).parent / "_placeholder"
    for i in range(1, len(script) + 1):
        p = script_store.scene_image_path(i)
        if p.exists() and p.stat().st_size > 0:
            images.append(str(p))
            continue
        missing.append(i)
        try:
            ph_dir.mkdir(parents=True, exist_ok=True)
            ph = ph_dir / f"scene_{i:02d}.png"
            img = Image.new("RGB", (1080, 1920), (24, 26, 40))
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype(r"C:\Windows\Fonts\malgun.ttf", 64)
            except Exception:
                try:
                    font = ImageFont.truetype(r"C:\Windows\Fonts\gulim.ttc", 64)
                except Exception:
                    font = ImageFont.load_default()
            scene = script[i - 1] if 0 < i <= len(script) else {}
            head = f"장면 {i} (이미지 없음)"
            body = str(scene.get("visual") or scene.get("content") or "")[:60]
            lines = [head] + textwrap.wrap(body, width=20)
            y = 760
            for line in lines:
                bbox = draw.textbbox((0, 0), line, font=font)
                x = (1080 - (bbox[2] - bbox[0])) // 2
                draw.text((x, y), line, fill=(212, 214, 224), font=font)
                y += 96
            img.save(ph)
            images.append(str(ph))
            log(f"⚠️ 장면 {i}: 이미지 없음 → 임시 플레이스홀더 생성 ({ph.name})")
        except Exception as e:
            log(f"⚠️ 장면 {i}: 플레이스홀더 생성 실패 ({e}) — 경로만 유지")
            images.append(str(p))
    if missing:
        log(f"⚠️ 이미지 없는 장면: {missing} → 정식 이미지는 '이미지 만들기'로 재생성하세요")
    return images, missing


# 테스트용
if __name__ == "__main__":
    gen = ImageGenerator(use_nvidia=False)
    
    test_script = [
        {"content": "파이썬 자동화 소개", "visual": "파이썬 로고와 코드"},
        {"content": "자동화의 장점", "visual": "로봇이 일하는 모습"},
        {"content": "실습 시작", "visual": "코딩하는 사람"},
    ]
    
    paths = gen.create_placeholder_images(test_script)
    print(f"\n생성된 이미지: {paths}")
