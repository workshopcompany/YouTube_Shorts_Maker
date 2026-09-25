"""
YouTube 인증 진단: client_secret.json과 token.pickle이 어느 프로젝트/클라이언트 기반인지 확인
"""
import json
import os
import pickle
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime

from modules.youtube_upload import YouTubeUploader

for f in ["client_secrets.json", "client_secret.json"]:
    p = os.path.join(ROOT, f)
    if os.path.exists(p):
        s = json.load(open(p, encoding="utf-8"))
        k = "installed" if "installed" in s else list(s)[0]
        info = s[k]
        m = datetime.fromtimestamp(os.path.getmtime(p)).strftime("%m-%d %H:%M")
        print(f"[{f}] (수정 {m})")
        print(f"   client_id  = {info.get('client_id')}")
        print(f"   project_id = {info.get('project_id')}")

tp = os.path.join(ROOT, "token.pickle")
if os.path.exists(tp):
    c = pickle.load(open(tp, "rb"))
    m = datetime.fromtimestamp(os.path.getmtime(tp)).strftime("%m-%d %H:%M")
    print(f"[token.pickle] (수정 {m})")
    print(f"   client_id     = {getattr(c, 'client_id', None)}")
    rt = str(getattr(c, "refresh_token", "") or "")
    print(f"   refresh_token = {rt[:14]}...")
else:
    print("[token.pickle] 없음")

# 채널 조회 (API 활성화 여부 실측)
print("\n--- 채널 조회 시도 (API 활성화 실측) ---")
yt = YouTubeUploader().get_authenticated_service()
if yt is None:
    print("❌ 서비스 생성 실패")
else:
    try:
        ch = yt.channels().list(part="snippet", mine=True).execute()
        items = ch.get("items", [])
        if items:
            print(f"✅ 로그인 채널: {items[0]['snippet']['title']} ({items[0]['id']})")
        else:
            print("⚠️ 이 계정에 유튜브 채널이 연결되어 있지 않습니다!")
    except Exception as e:
        print(f"❌ 채널 조회 실패: {str(e)[:300]}")
