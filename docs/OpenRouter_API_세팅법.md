# 🚀 OpenRouter API 모델 세팅법

**작성일**: 2026-09-11

---

## 📌 개요

OpenRouter는 여러 AI 모델을 하나의 API로 통합해서 사용할 수 있는 플랫폼입니다.
유료 모델뿐만 아니라 **무료 모델(:free)** 도 지원합니다.

---

## 🔑 API 키 발급

### 1. 회원가입
- [openrouter.ai](https://openrouter.ai/) 접속
- Google/GitHub 계정으로 로그인

### 2. API 키 생성
1. [openrouter.ai/keys](https://openrouter.ai/keys) 접속
2. "Create Key" 클릭
3. 키 복사 (시작 형식: `sk-or-v1-...`)

### 3. config.py에 설정
```python
# OpenRouter API 키
OUTROUTER_API_KEY = "sk-or-v1-########..."
```

---

## 🆓 무료 모델 확인 방법

### 방법 1: 웹사이트에서 확인
1. [openrouter.ai/models](https://openrouter.ai/models) 접속
2. "Free" 필터 클릭
3. 무료 모델 목록 확인

### 방법 2: API로 확인
```bash
curl https://openrouter.ai/api/v1/models \
  -H "Authorization: Bearer YOUR_API_KEY"
```

---

## 📝 코드 설정 방법

### 기본 요청 형식 (Python)
```python
import requests

url = "https://openrouter.ai/api/v1/chat/completions"
headers = {
    "Authorization": f"Bearer {OUTROUTER_API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "http://localhost:3000",  # 선택 (추천)
    "X-Title": "My App"                         # 선택 (추천)
}

payload = {
    "model": "openrouter/free",  # 무료 모델 랜덤 할당
    "messages": [
        {"role": "user", "content": "안녕하세요!"}
    ],
    "max_tokens": 4096
}

response = requests.post(url, headers=headers, json=payload)
print(response.json()["choices"][0]["message"]["content"])
```

---

## 🎯 무료 모델 지정 방법

### openrouter/free (무료 모델 자동 할당)
```python
model = "openrouter/free"
```
- 사용 가능한 무료 모델 중 **자동으로 하나 할당**
- 결과가 호출마다 다를 수 있음

### 특정 무료 모델 지정
```python
model = "google/gemma-4-26b-a4b-it:free"        # 구글 모델
model = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"  # 엔비디아
model = "inclusionai/ling-3.0-flash-vl:free"     # 링 모델
```
- 무료 모델은 끝에 `:free` 접미사가 붙음
- 특정 모델 지정 시 결과가 안정적

---

## ⚠️ 주의사항

### 1. 키 형식 확인
- OpenRouter 키: `sk-or-v1-...`
- **Groq 키와 혼용 금지!** (완전히 다른 서비스)

### 2. 모델명 확인
- 무료 모델: 끝에 `:free` 붙음 (예: `google/gemma-2-9b-it:free`)
- 유료 모델: 크레딧 필요, `403 insufficient_credits` 오류 발생

### 3. 헤더 추가
```python
headers = {
    "Authorization": "Bearer sk-or-v1-...",  # 필수
    "Content-Type": "application/json",       # 필수
    "HTTP-Referer": "http://localhost:3000",  # 추천
    "X-Title": "My App"                       # 추천
}
```

---

## 🔧 오류 코드 참고표

| 코드 | 원인 | 해결 |
|------|------|------|
| 401 invalid_api_key | 키가 잘못됨/만료 | openrouter.ai/keys에서 재발급 |
| 401 missing_api_key | Authorization 헤더 누락 | Bearer sk-or-v1-... 형식 확인 |
| 403 insufficient_credits | 유료 모델인데 크레딧 0 | :free 모델로 변경 |
| 404 model not found | 모델명 오류 | 정확한 모델 ID 확인 |
| 429 rate limit | 요청 한도 초과 | 잠시 후 재시도 |

---

## 🎬 이 프로젝트에서의 사용

### text_gen.py 설정
```python
elif api_type == "openrouter":
    self.api_key = OUTROUTER_API_KEY
    self.url = "https://openrouter.ai/api/v1/chat/completions"
    self.model = "openrouter/free"  # 무료 모델 자동 할당
```

### main.py에서 API 선택
```
📌 사용할 API를 선택하세요:
   1. Gemini API (기본)
   2. OpenRouter API
   3. Groq API

선택 (1/2/3): 2
```

---

## 📊 테스트 결과 (2026-09-11)

| 테스트 | 결과 |
|--------|------|
| 기본 응답 테스트 | ✅ 정상 (한글 응답 확인) |
| 제목 생성 | ✅ 정상 (5개 생성) |
| 설명 생성 | ✅ 정상 |
| 대본 생성 | ⚠️ 모델에 따라 결과 상이 |

### 할당된 무료 모델 예시
- `inclusionai/ling-3.0-flash-vl:free`
- `liquid/lfm-2.5-2.6b:free`
- `nvidia/nemotron-3-ultra-550b-a55b:free`
- `nvidia/nemotron-3-super-120b-a12b:free`

---

**📌 요약: OpenRouter는 무료 모델을 여러 개 제공하며, `openrouter/free`로 자동 할당받거나 `:free` 접미사로 특정 모델을 지정할 수 있습니다.**