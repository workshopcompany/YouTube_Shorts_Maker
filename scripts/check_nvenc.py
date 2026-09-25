"""
NVENC(GPU 하드웨어 인코더) 사용 가능 여부 확인
- NVIDIA 드라이버 업데이트 "후" 실행: python scripts/check_nvenc.py
- "h264_nvenc 인코딩 성공"이 나오면 코드 수정 없이 다음 영상 제작부터 자동으로 GPU 인코딩됩니다
  (video_edit.py의 _encoder_args()가 매번 자동으로 프리프로브하기 때문)
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import FFMPEG_OVERRIDE_DIR


def main():
    # config 지정 FFmpeg 우선 적용 (예: FFmpeg 8.x)
    if FFMPEG_OVERRIDE_DIR and os.path.exists(FFMPEG_OVERRIDE_DIR):
        os.environ["PATH"] = FFMPEG_OVERRIDE_DIR + os.pathsep + os.environ["PATH"]
        print(f"🔧 FFmpeg 우선 경로: {FFMPEG_OVERRIDE_DIR}")

    # 1) GPU/드라이버 버전
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version",
                            "--format=csv,noheader"],
                           capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
        if r.returncode == 0 and r.stdout.strip():
            print(f"🖥️ GPU/드라이버: {r.stdout.strip()}")
        else:
            print("⚠️ nvidia-smi 실행 실패 — NVIDIA 드라이버가 설치되지 않았거나 PATH 문제")
    except FileNotFoundError:
        print("⚠️ nvidia-smi 없음 — NVIDIA 드라이버 미설치")

    # 2) ffmpeg에서 h264_nvenc 실제 인코딩 테스트 (진짜 판정 기준)
    cmd = ["ffmpeg", "-v", "error", "-hide_banner",
           "-f", "lavfi", "-i", "nullsrc=s=256x256:d=0.1",
           "-c:v", "h264_nvenc", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    if r.returncode == 0:
        print("✅ h264_nvenc 인코딩 성공 — 다음 영상 제작부터 자동으로 GPU(NVENC) 인코딩됩니다")
        print("   확인 방법: 영상 제작 시 '🎬 인코더: h264_nvenc(GPU)' 로그가 뜨는지 보세요")
    else:
        print("❌ h264_nvenc 인코딩 실패 — FFmpeg가 요구하는 NVENC API 버전에 드라이버가 미달")
        if r.stderr:
            print(f"   오류: {r.stderr.strip()[:200]}")
        print("👉 해결 옵션 2가지 (둘 중 하나만 되면 됨):")
        print("   A) NVIDIA 드라이버 최신 업데이트 (FFmpeg 9.x는 드라이버 610.00+ 요구)")
        print("      ⚠️ 구형 GPU(1080Ti 등 Pascal)는 610+ 드라이버가 출시되지 않을 수 있음")
        print("   B) FFmpeg를 8.x 이하로 교체 (NVENC API 13.0 지원 → 현재 드라이버로도 GPU 사용 가능)")
        print("      - https://www.gyan.dev/ffmpeg/builds/ 에서 'release builds 8.x' 다운로드 후")
        print("        기존 ffmpeg 경로보다 우선되게 PATH에 등록")
        print("   둘 다 어려우면 그대로 libx264(CPU) 사용 — 품질은 동일, 속도만 느림")


if __name__ == "__main__":
    main()
