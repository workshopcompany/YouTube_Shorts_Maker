"""
유튜브 AI 라벨(변경/합성 콘텐츠) 진단
- 내 채널 최근 업로드 영상들의 status를 전체 덤프해서
  AI/합성 콘텐츠 관련 필드(altered/synthetic)의 존재 여부와 값을 확인
- 실행: python scripts/check_ai_label.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.youtube_upload import YouTubeUploader


def main():
    yt = YouTubeUploader().get_authenticated_service()
    if yt is None:
        print("❌ 인증 실패")
        return

    # 1) 내 채널 + 업로드 재생목록 ID
    ch = yt.channels().list(part="contentDetails,snippet", mine=True).execute()
    items = ch.get("items", [])
    if not items:
        print("❌ 채널 없음")
        return
    ch_title = items[0]["snippet"]["title"]
    uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    print(f"📺 채널: {ch_title}")
    print(f"📂 업로드 재생목록: {uploads}")

    # 2) 최근 영상 ID 목록
    pl = yt.playlistItems().list(
        part="contentDetails", playlistId=uploads, maxResults=10).execute()
    vids = [it["contentDetails"]["videoId"] for it in pl.get("items", [])]
    if not vids:
        print("❌ 업로드된 영상 없음")
        return
    print(f"🎬 최근 영상 {len(vids)}개: {vids}\n")

    # 3) status 전체 덤프 (AI/합성 관련 필드 확인)
    for vid in vids:
        r = yt.videos().list(part="status,snippet", id=vid).execute()
        for v in r.get("items", []):
            st = v["status"]
            title = v["snippet"]["title"][:40]
            print(f"--- {title} ... ({vid})")
            print(json.dumps(st, ensure_ascii=False, indent=2))
            # AI/합성 관련 키 강조
            ai_keys = [k for k in st if any(
                w in k.lower() for w in ("altered", "synthetic", "ai", "disclos"))]
            print(f"   🔍 AI/합성 관련 필드: {ai_keys if ai_keys else '없음 (API에 필드 없음)'}\n")


if __name__ == "__main__":
    main()
