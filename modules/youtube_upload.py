"""
YouTube 자동화 - 유튜브 업로드 모듈
YouTube Data API v3를 사용하여 영상 업로드
"""

import os
import pickle
from pathlib import Path
from config import OUTPUT_DIR


class YouTubeUploader:
    # 프로젝트 루트 기준 파일 위치
    ROOT = Path(__file__).resolve().parent.parent
    # 구글에서 다운로드한 JSON은 client_secret.json / client_secrets.json 어느 이름이든 지원
    CLIENT_SECRETS_CANDIDATES = [ROOT / "client_secrets.json", ROOT / "client_secret.json"]
    TOKEN_FILE = ROOT / "token.pickle"

    @classmethod
    def find_client_secrets(cls) -> Path:
        """존재하는 클라이언트 시크릿 파일 경로 반환 (없으면 기본 경로 반환)"""
        for p in cls.CLIENT_SECRETS_CANDIDATES:
            if p.exists():
                return p
        return cls.CLIENT_SECRETS_CANDIDATES[0]
    SCOPES = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
    ]

    def __init__(self):
        self.output_dir = Path(OUTPUT_DIR)
    
    def get_authenticated_service(self):
        """YouTube API 인증 (최초 1회 브라우저 로그인 → token.pickle 저장 → 이후 자동)"""
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
            
            credentials = None
            
            if self.TOKEN_FILE.exists():
                with open(self.TOKEN_FILE, 'rb') as token:
                    credentials = pickle.load(token)
            
            if not credentials or not credentials.valid:
                if credentials and credentials.expired and credentials.refresh_token:
                    try:
                        print("🔄 만료된 토큰 갱신 중...")
                        credentials.refresh(Request())
                    except Exception as e:
                        print(f"⚠️ 토큰 갱신 실패({e}) → 재로그인합니다.")
                        credentials = None
                if not credentials:
                    secrets_file = self.find_client_secrets()
                    if not secrets_file.exists():
                        print("⚠️ client_secrets.json 파일이 없습니다!")
                        print("   👉 'Google_OAuth_세팅_가이드.md'를 따라 발급 후")
                        print(f"   👉 이 위치에 저장: {secrets_file}")
                        return None
                    print("🌐 브라우저에서 구글 로그인 창을 엽니다...")
                    print("   ⚠️ 업로드할 유튜브 채널의 구글 계정으로 로그인하고 승인하세요!")
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(secrets_file), self.SCOPES
                    )
                    credentials = flow.run_local_server(port=0)
                
                # 로그인 성공 → 저장 (다음부터 자동 로그인)
                with open(self.TOKEN_FILE, 'wb') as token:
                    pickle.dump(credentials, token)
                print("✅ 로그인 완료! token.pickle 저장됨 (다음부터는 자동 로그인)")
            
            youtube = build('youtube', 'v3', credentials=credentials)

            # 업로드 대상 채널 확인 (다른 계정/채널에 올라가는 실수 방지)
            try:
                ch = youtube.channels().list(part="snippet", mine=True).execute()
                items = ch.get("items", [])
                if items:
                    ch_title = items[0]["snippet"]["title"]
                    ch_id = items[0]["id"]
                    print(f"📺 업로드 대상 채널: {ch_title} (ID: {ch_id})")
                else:
                    print("⚠️ 이 구글 계정에 연결된 유튜브 채널이 없습니다! (채널 생성 필요)")
            except Exception as e:
                print(f"ℹ️ 채널 정보 조회 생략: {e}")

            return youtube
            
        except ImportError:
            print("⚠️ Google API 라이브러리가 설치되지 않았습니다.")
            print("pip install google-auth google-auth-oauthlib google-api-python-client")
            return None
        except Exception as e:
            print(f"❌ YouTube 인증 실패: {e}")
            return None

    
    def upload_video(self, video_path: str, title: str, description: str, 
                     tags: list = None, category_id: str = "22", privacy: str = "private") -> dict:
        """
        유튜브에 영상 업로드
        privacy: "private"(비공개), "unlisted"(링크공개), "public"(공개)
        """
        if not os.path.exists(video_path):
            return {"success": False, "error": "영상 파일이 없습니다."}
        
        youtube = self.get_authenticated_service()
        if not youtube:
            return {"success": False, "error": "YouTube 인증 실패"}
        
        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags or [],
                "categoryId": category_id
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False
            }
        }
        
        from googleapiclient.http import MediaFileUpload
        
        media = MediaFileUpload(video_path, mimetype='video/mp4', resumable=True)
        
        print(f"📤 유튜브 업로드 중...")
        print(f"   제목: {title}")
        
        try:
            request = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media
            )
            
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    print(f"   진행률: {int(status.progress() * 100)}%")
            
            video_id = response['id']
            video_url = f"https://www.youtube.com/watch?v={video_id}"

            print(f"✅ 업로드 완료! {video_url}")
            print(f"   🎛️ 스튜디오 확인: https://studio.youtube.com/video/{video_id}/edit")

            # 실제 반영된 공개 설정 역조회 (요청값 vs YouTube 저장값 검증)
            actual = None
            try:
                check = youtube.videos().list(part="status", id=video_id).execute()
                items = check.get("items", [])
                if items:
                    st = items[0]["status"]
                    actual = st.get("privacyStatus")
                    up_status = st.get("uploadStatus")
                    label = {"private": "비공개", "public": "공개",
                             "unlisted": "일부 공개(링크)"}.get(actual, actual)
                    print(f"🔍 YouTube 실제 반영 확인: 공개설정={label} / 처리상태={up_status}")
                    if actual != privacy:
                        print(f"   ⚠️ 요청({privacy}) ≠ 실제({actual}) — 스튜디오에서 공개설정을 다시 확인하세요!")
                else:
                    print("⚠️ 업로드된 영상 역조회 실패 — 스튜디오에서 직접 확인하세요.")
            except Exception as e:
                print(f"ℹ️ 공개설정 역조회 생략: {e}")

            return {"success": True, "video_id": video_id, "url": video_url,
                    "privacy": actual or privacy}
            
        except Exception as e:
            print(f"❌ 업로드 실패: {e}")
            return {"success": False, "error": str(e)}
    
    def upload_from_output(self, video_file: str = "final_video.mp4", title: str = None, description: str = None):
        """output 폴더에서 영상 찾아서 업로드"""
        video_path = str(self.output_dir / "videos" / video_file)
        
        if not os.path.exists(video_path):
            print(f"❌ 영상을 찾을 수 없습니다: {video_path}")
            return None
        
        if not title:
            title_file = self.output_dir / "title.txt"
            if title_file.exists():
                title = title_file.read_text(encoding='utf-8').strip()
            else:
                title = "자동 생성 영상"
        
        if not description:
            desc_file = self.output_dir / "description.txt"
            if desc_file.exists():
                description = desc_file.read_text(encoding='utf-8').strip()
            else:
                description = "자동으로 생성된 영상입니다."
        
        return self.upload_video(video_path, title, description)
