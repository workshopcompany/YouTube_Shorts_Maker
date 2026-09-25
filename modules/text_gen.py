"""
YouTube 자동화 - 텍스트 생성 모듈
Gemini, OpenRouter, Groq API를 지원하여 제목, 설명, 대본 생성
"""

import time
import requests
from config import GEMINI_API_KEY, OUTROUTER_API_KEY, GROQ_API_KEY, TITLE_PROMPT, DESCRIPTION_PROMPT, SCRIPT_PROMPT, MAIN_CHARACTER


class TextGenerator:
    # Groq에서 제외할 비대화형 모델 키워드 (TTS/가드/음성인식/임베딩)
    GROQ_EXCLUDE = ('whisper', 'tts', 'guard', 'orpheus', 'distil', 'playai', 'embed')
    # Groq 기본 모델 (목록 조회 실패 시 폴백)
    GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"

    def __init__(self, api_type="gemini", groq_model=None):
        """
        api_type: "gemini", "openrouter", "groq"
        groq_model: Groq 사용 시 모델 ID (None이면 기본값)
        """
        self.api_type = api_type
        
        if api_type == "gemini":
            self.model_name = "gemini-3.5-flash"
            self.gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={GEMINI_API_KEY}"
        elif api_type == "openrouter":
            self.api_key = OUTROUTER_API_KEY
            self.url = "https://openrouter.ai/api/v1/chat/completions"
            self.model = "openrouter/free"
            self.max_tokens = 4096
        elif api_type == "groq":
            self.api_key = GROQ_API_KEY
            self.url = "https://api.groq.com/openai/v1/chat/completions"
            self.model = groq_model or self.GROQ_DEFAULT_MODEL
            self.max_tokens = 900  # Groq 무료 티어 OTPM 1000 이하 안전치
            # qwen 계열은 '생각' 토큰이 출력 한도를 먹으므로 추론 비활성화 (프로브 200 확인)
            self.extra_payload = {'reasoning_effort': 'none'} if 'qwen' in self.model.lower() else {}

    @classmethod
    def list_groq_models(cls):
        """Groq API에서 사용 가능한 대화형 모델 목록을 실시간 조회 (실패 시 None)"""
        try:
            r = requests.get("https://api.groq.com/openai/v1/models",
                             headers={"Authorization": f"Bearer {GROQ_API_KEY}"}, timeout=15)
            if r.status_code != 200:
                return None
            ids = [m.get('id', '') for m in r.json().get('data', [])]
            return [i for i in ids if not any(k in i.lower() for k in cls.GROQ_EXCLUDE)]
        except Exception:
            return None
    
    def _call_api(self, prompt: str, max_tokens: int = None) -> str:
        """선택된 API 호출 (429 할당량 초과 시 대기 후 자동 재시도)"""
        if self.api_type == "gemini":
            # 3.5-flash 과부하 시 순차 시도할 Gemini 계열 모델 목록
            gemini_models = ["gemini-3.5-flash", "gemini-3.0-flash", "gemini-3.5-flash-lite"]
            payload = {
                "contents": [{"parts": [{"text": prompt}]}]
            }
            last_err = None
            for model_name in gemini_models:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
                try:
                    print(f"   📡 Gemini ({model_name}) 호출 중...")
                    resp = requests.post(url, json=payload, timeout=60)
                    if resp.status_code == 200:
                        data = resp.json()
                        text = data["candidates"][0]["content"]["parts"][0]["text"]
                        if text:
                            return text
                    err_msg = resp.text[:150]
                    last_err = f"HTTP {resp.status_code} ({model_name}): {err_msg}"
                    print(f"   ⚠️ Gemini ({model_name}) 오류 [{resp.status_code}] → 다음 모델 시도")
                except Exception as e:
                    last_err = f"{model_name} 오류: {e}"
                    print(f"   ⚠️ Gemini ({model_name}) 통신 오류 ({e}) → 다음 모델 시도")
                time.sleep(1)

            # 모든 Gemini 모델 실패 시 다른 모델(Groq 등) 사용 제안 메시지 발생
            raise Exception(
                f"Gemini 서버가 현재 일시적 과부하(503/504) 상태입니다. "
                f"대본 생성 창에서 '텍스트 API'를 'Groq'로 변경하여 다시 시도해 주세요. (상세: {last_err})"
            )
        else:
            # OpenRouter, Groq (OpenAI 호환 API)
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/youtube-automation-saas",
                "X-Title": "YouTube Automation SaaS"
            }
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens or self.max_tokens
            }
            payload.update(getattr(self, 'extra_payload', {}))
            # 429(할당량 초과) 대기 후 재시도 루프
            response = None
            for attempt in range(3):
                response = requests.post(self.url, headers=headers, json=payload, timeout=120)
                # 미지원 파라미터(400)면 제거하고 1회 재시도
                if response.status_code == 400 and self.extra_payload:
                    print("   ⚠️ 이 모델은 추론 옵션 미지원 → 제거 후 재시도")
                    dropped = dict(self.extra_payload)
                    self.extra_payload = {}
                    payload = {k: v for k, v in payload.items() if k not in dropped}
                    response = requests.post(self.url, headers=headers, json=payload, timeout=120)
                    break
                if response.status_code != 429:
                    break
                ra = response.headers.get("retry-after", "")
                wait = int(ra) if ra.isdigit() else 60
                print(f"   ⏳ 할당량 초과(429) → {wait}초 후 자동 재시도 ({attempt + 1}/3)")
                time.sleep(wait)
            else:
                raise Exception(f"API 할당량 초과 (재시도 3회 실패): {response.text[:150]}")

            if response.status_code == 200:
                data = response.json()
                # 응답이 비어있으면 재시도
                for _ in range(3):
                    content = data["choices"][0]["message"].get("content")
                    if content:
                        return content
                    response = requests.post(self.url, headers=headers, json=payload, timeout=120)
                    if response.status_code != 200:
                        break
                    data = response.json()
                raise Exception(f"API 응답이 계속 비어있습니다 ({self.api_type})")
            raise Exception(f"API 오류 ({self.api_type}): {response.status_code} - {response.text[:200]}")
    
    def generate_title(self, idea: str) -> list:
        """유튜브 제목 5개 생성"""
        prompt = TITLE_PROMPT.format(idea=idea)
        response = self._call_api(prompt)
        
        # 응답 파싱
        titles = []
        for line in response.strip().split('\n'):
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith('-')):
                # 번호나 불릿 제거
                title = line.lstrip('0123456789.-) ')
                if title:
                    titles.append(title)
        
        return titles[:5]
    
    def generate_description(self, idea: str) -> str:
        """유튜브 설명 생성"""
        prompt = DESCRIPTION_PROMPT.format(idea=idea)
        response = self._call_api(prompt)
        return response.strip()
    
    def _parse_scenes(self, response: str) -> list:
        """응답 텍스트에서 장면 파싱"""
        scenes = []
        current_scene = {}
        
        for line in response.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # 장면 시작 감지
            if '[장면' in line or '장면' in line:
                if current_scene:
                    scenes.append(current_scene)
                current_scene = {"scene": len(scenes) + 1}
                
                # 시간 정보 추출
                if '(' in line and ')' in line:
                    time_str = line[line.find('(')+1:line.find(')')]
                    current_scene["time"] = time_str
            
            # 내용 추출
            elif '내용:' in line or '내용 :' in line:
                current_scene["content"] = line.split(':', 1)[1].strip()
            
            # 시각 설명 추출
            elif '시각:' in line or '시각 :' in line:
                current_scene["visual"] = line.split(':', 1)[1].strip()
        
        # 마지막 장면 추가
        if current_scene:
            scenes.append(current_scene)
        return scenes

    def _time_range(self, idx: int, scene_len: int = 5) -> str:
        """장면 번호로 시간 균등 배분 (12장면 × 5초 = 60초)"""
        start = (idx - 1) * scene_len
        return f"{start}~{start + scene_len}초"

    def _parse_numbered(self, response: str, key: str) -> list:
        """[장면 N] + '키:' 형식 응답 파싱 → [{"scene": N, key: "..."}]"""
        items = []
        last_n = 0
        for line in response.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            n = 0
            if '장면' in line:
                digits = ''.join(ch for ch in line.split('장면', 1)[1][:4] if ch.isdigit())
                if digits:
                    n = int(digits)
                    last_n = n
            if f'{key}:' in line or f'{key} :' in line:
                val = line.split(':', 1)[1].strip()
                if val:
                    items.append({"scene": n or last_n, key: val})
        return items

    def generate_script(self, idea: str, title_context: str = None, total_scenes: int = 12,
                        character: str = MAIN_CHARACTER) -> list:
        """
        유튜브 쇼츠 대본 생성 — 1회 원샷 호출 (필요시 빈칸 보충 최대 1회)
        반환: [{"scene": 1, "time": "0~5초", "content": "...", "visual": "..."}, ...]
        """
        scene_len = 5  # 12장면 × 5초 = 60초
        title_line = f"영상 제목(확정): {title_context}\n위 제목과 일관되게 아래 요청을 수행해줘.\n\n" if title_context else ""
        prompt = title_line + SCRIPT_PROMPT.format(idea=idea, character=character)

        # 1) 대본(대사 + 시각 묘사) 1회 원샷 생성
        print(f"   📄 대본(대사 + 시각 묘사) 생성 중... ({self.api_type})")
        response = self._call_api(prompt)
        parsed = self._parse_scenes(response)

        # 1~total_scenes 장면 틀에 정렬 및 누락 방지
        scenes = []
        for i in range(1, total_scenes + 1):
            sc = next((s for s in parsed if s.get("scene") == i), None)
            time_str = (sc.get("time") if sc else "") or self._time_range(i, scene_len)
            content = (sc.get("content") if sc else "") or ""
            visual = (sc.get("visual") if sc else "") or ""
            scenes.append({"scene": i, "time": time_str, "content": content, "visual": visual})

        # 2) 빈칸이 있을 경우만 보충 호출 최대 1회 시도
        empty = [sc["scene"] for sc in scenes if not sc["content"] or not sc["visual"]]
        if empty:
            seg = ", ".join(f"장면 {n}" for n in empty)
            extra = (
                f"\n\n아래 장면의 내용(대사) 또는 시각(묘사)이 비어있습니다: {seg}\n"
                f"비어있는 부분만 아래 형식으로 작성해줘:\n"
                f"[장면 N] (0~5초)\n- 내용: (대사)\n- 시각: (구체적 이미지 묘사)\n"
            )
            print(f"   ↻ 비어있는 장면 보충 중... ({seg})")
            try:
                supp_resp = self._call_api(prompt + extra)
                supp_parsed = self._parse_scenes(supp_resp)
                for s in supp_parsed:
                    sn = s.get("scene")
                    if sn and 1 <= sn <= total_scenes:
                        if not scenes[sn - 1]["content"] and s.get("content"):
                            scenes[sn - 1]["content"] = s["content"]
                        if not scenes[sn - 1]["visual"] and s.get("visual"):
                            scenes[sn - 1]["visual"] = s["visual"]
            except Exception as e:
                print(f"   ⚠️ 보충 호출 실패 (작업자가 화면에서 확인 가능): {e}")

        # 그래도 안 채워지면 작업자가 확인하고 웹에서 직접 수정/보충할 수 있도록 반환
        return scenes

    def fill_empty_scenes(self, idea: str, script: list, title_context: str = None,
                          character: str = MAIN_CHARACTER) -> list:
        """대본에서 내용/시각이 빈 장면을 API로 자동 채움 (main 메뉴 5번용)"""
        title_line = f"영상 제목(확정): {title_context}\n위 제목과 일관되게 아래 요청을 수행해줘.\n\n" if title_context else ""
        base = SCRIPT_PROMPT.format(idea=idea, character=character)

        # 1) 빈 내용 채우기
        empty_c = [sc for sc in script if not (sc.get("content") or "").strip()]
        if empty_c:
            nums = ", ".join(f"[장면 {sc['scene']}]" for sc in empty_c)
            prompt = (
                f"{title_line}{base}\n\n"
                f"아래 장면들의 '내용'만 다시 작성해줘:\n{nums}\n"
                f"- 형식은 정확히: [장면 N] / 내용: (구어체 대사 한두 문장)\n"
                f"- '시각'은 절대 쓰지 말 것"
            )
            print(f"   ↻ 빈 내용 채우는 중... (장면 {', '.join(str(sc['scene']) for sc in empty_c)})")
            response = self._call_api(prompt)
            for it in self._parse_numbered(response, "내용"):
                for sc in empty_c:
                    if it["scene"] == sc["scene"] and not (sc.get("content") or "").strip():
                        sc["content"] = it["내용"]

        # 2) 빈 시각 채우기: 장면당 1회 호출 (상세한 묘사를 위해)
        empty_v = [sc for sc in script if (sc.get("content") or "").strip() and not (sc.get("visual") or "").strip()]
        for sc in empty_v:
            prompt = (
                f"{title_line}아래는 확정된 유튜브 쇼츠 대사 1개입니다:\n"
                f"[장면 {sc['scene']}] 내용: {sc['content']}\n\n"
                f"이 대사에 어울리는 '시각' 묘사를 상세하게 작성해줘.\n"
                f"- 형식은 정확히: [장면 {sc['scene']}] / 시각: (이미지 생성용 화면 묘사)\n"
                f"- 시각은 2~3문장 이상으로 상세하게: 인물/사물, 행동, 표정, 조명, 구도, 스타일까지 구체적으로\n"
                f"- 주인공 '{character}' 캐릭터가 화면에 등장하는 모습으로 묘사 (행동·표정 포함)\n"
                f"- 글자 수 제한은 없음. 짧게 줄이지 말 것\n"
                f"- 대사는 절대 다시 쓰지 말고 '시각'만 쓸 것\n"
                f"- 지금은 [장면 {sc['scene']}] 1개만 작성"
            )
            print(f"   ↻ 빈 시각 채우는 중... (장면 {sc['scene']})")
            try:
                response = self._call_api(prompt)
                for it in self._parse_numbered(response, "시각"):
                    if it["scene"] == sc["scene"] and not (sc.get("visual") or "").strip():
                        sc["visual"] = it["시각"]
                if not (sc.get("visual") or "").strip():
                    raw = (response or "").replace("\n", " ").strip()
                    if "시각" in raw:
                        sc["visual"] = raw.split("시각", 1)[1].lstrip(": ").strip()
            except Exception as e:
                print(f"   ⚠ 장면 {sc['scene']} 시각 보충 실패: {e}")

        # 3) 그래도 비어있으면 기본값
        for sc in script:
            if not (sc.get("content") or "").strip():
                sc["content"] = "자동화된 쇼츠 제작 과정이 화면에 표시된다"
            if not (sc.get("visual") or "").strip():
                sc["visual"] = "노트북 화면에 코드가 실행되며 영상이 완성되는 클로즈업"
        return script

    def regenerate_scene(self, idea: str, script: list, scene_no: int, title_context: str = None,
                         character: str = MAIN_CHARACTER) -> list:
        """지정한 장면 1개의 내용+시각만 API로 새로 작성 (main 메뉴 6번용)"""
        if not (1 <= scene_no <= len(script)):
            print("   잘못된 장면 번호입니다.")
            return script
        sc = script[scene_no - 1]
        title_line = f"영상 제목(확정): {title_context}\n위 제목과 일관되게 아래 요청을 수행해줘.\n\n" if title_context else ""
        base = SCRIPT_PROMPT.format(idea=idea, character=character)
        prompt = (
            f"{title_line}{base}\n\n"
            f"전체 장면 중 [장면 {scene_no}] 하나만 다시 작성해줘.\n"
            f"- 형식은 정확히 두 줄:\n"
            f"  [장면 {scene_no}] / 내용: (구어체 대사 한두 문장)\n"
            f"  [장면 {scene_no}] / 시각: (이미지 생성용 화면 묘사)\n"
            f"- 다른 장면은 절대 쓰지 말 것"
        )
        print(f"   ↻ 장면 {scene_no} 다시 작성 중... ({self.api_type})")
        response = self._call_api(prompt)
        got_c = self._parse_numbered(response, "내용")
        got_v = self._parse_numbered(response, "시각")
        if got_c:
            sc["content"] = got_c[0]["내용"]
        if got_v:
            sc["visual"] = got_v[0]["시각"]
        if got_c or got_v:
            print(f"   ✅ 장면 {scene_no} 갱신됨")
        else:
            print("   ⚠️ 응답 파싱 실패 — 기존 내용 유지")
        return script
        return scenes
    
    def generate_all(self, idea: str) -> dict:
        """모든 텍스트를 한번에 생성"""
        print(f"📝 제목 생성 중... (API: {self.api_type})")
        titles = self.generate_title(idea)
        
        print(f"📝 설명 생성 중... (API: {self.api_type})")
        description = self.generate_description(idea)
        
        print(f"📝 대본 생성 중... (API: {self.api_type})")
        script = self.generate_script(idea)
        
        return {
            "titles": titles,
            "description": description,
            "script": script
        }


# 테스트용
if __name__ == "__main__":
    gen = TextGenerator(api_type="gemini")
    result = gen.generate_all("파이썬으로 자동화 프로그램 만들기")
    
    print("\n=== 생성된 제목 ===")
    for i, title in enumerate(result["titles"], 1):
        print(f"{i}. {title}")
    
    print("\n=== 생성된 설명 ===")
    print(result["description"])
    
    print("\n=== 생성된 대본 ===")
    for scene in result["script"]:
        print(f"\n[장면 {scene.get('scene')}] {scene.get('time', '')}")
        print(f"  내용: {scene.get('content', '')}")
        print(f"  시각: {scene.get('visual', '')}")
