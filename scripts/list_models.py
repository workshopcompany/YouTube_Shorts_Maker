import sys
sys.path.insert(0, '.')
import requests

# 1) Groq 사용 가능 모델 목록
from config import GROQ_API_KEY
try:
    r = requests.get('https://api.groq.com/openai/v1/models',
                     headers={'Authorization': f'Bearer {GROQ_API_KEY}'}, timeout=30)
    print('=== GROQ models (status', r.status_code, ') ===')
    if r.status_code == 200:
        for m in r.json().get('data', []):
            mid = m.get('id', '')
            # 대화용 모델만 (음성/가드 제외)
            if not any(k in mid.lower() for k in ['whisper', 'tts', 'guard', 'distil']):
                print(' ', mid)
    else:
        print(r.text[:300])
except Exception as e:
    print('GROQ ERROR:', e)

# 2) Groq 현재 설정 모델 실제 호출 테스트
print()
print('=== GROQ chat test (llama-3.3-70b-versatile) ===')
try:
    r = requests.post('https://api.groq.com/openai/v1/chat/completions',
                      headers={'Authorization': f'Bearer {GROQ_API_KEY}', 'Content-Type': 'application/json'},
                      json={'model': 'llama-3.3-70b-versatile',
                            'messages': [{'role': 'user', 'content': '안녕'}], 'max_tokens': 10}, timeout=30)
    print('status:', r.status_code)
    print(r.text[:200])
except Exception as e:
    print('ERROR:', e)
