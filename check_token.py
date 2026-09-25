# -*- coding: utf-8 -*-
"""토큰 상태 확인: 유효기간 / 재발급 토큰 여부 / 한국시간 만료시각 표시
실행: python check_token.py
"""
import sys, io, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
from datetime import timezone, timedelta

TOKEN_FILE = Path(__file__).resolve().parent / "token.pickle"
KST = timezone(timedelta(hours=9))

if not TOKEN_FILE.exists():
    print("❌ token.pickle 없음 → 아직 로그인 전")
    print("   👉 업로드 실행시 브라우저 로그인이 자동으로 시작됩니다.")
    sys.exit(0)

with open(TOKEN_FILE, 'rb') as f:
    creds = pickle.load(f)

print("✅ token.pickle 있음")
if getattr(creds, 'valid', False):
    print("   상태: 유효 ✅ → 다음 업로드는 바로 진행됨")
elif getattr(creds, 'expired', False):
    print("   상태: 만료됨 ⏰ → 다음 업로드시 자동 갱신 시도")

if getattr(creds, 'refresh_token', None):
    print("   재발급(refresh) 토큰: 있음 ✅ → 만료 시 자동 갱신 사용")
else:
    print("   재발급(refresh) 토큰: 없음 ⚠️ → 만료되면 브라우저 재로그인 필요")

exp = getattr(creds, 'expiry', None)
if exp:
    try:
        kst = exp.astimezone(KST) if exp.tzinfo else exp.replace(tzinfo=timezone.utc).astimezone(KST)
        print(f"   만료시각(한국시간): {kst:%Y-%m-%d %H:%M}")
        print("   💡 테스트 모드 앱은 발급 후 7일째 되는 날 재로그인이 필요할 수 있음")
    except Exception:
        print(f"   만료시각: {exp}")
