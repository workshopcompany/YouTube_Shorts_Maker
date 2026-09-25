"""자막(ASS) + NVENC 인코딩 통합 테스트 — 장면 3개로 짧은 영상 생성"""
import glob, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modules.video_edit import VideoEditor
from modules.tts import TTSEngine

TEXTS = [
    "안녕하세요! 오늘은 파이썬 자동화에 대해 알아볼게요.",
    "자동화를 하면 3시간 걸리던 작업이 10분이면 끝납니다.",
    "지금 바로 시작해볼까요?",
]

if __name__ == "__main__":
    # 1) Edge TTS 음성 3개 (scene_0*.mp3 재사용)
    engine = TTSEngine()
    auds = engine.generate_scene_audio([{"content": t} for t in TEXTS])
    assert len(auds) == 3, f"음성 생성 실패: {auds}"

    # 2) 병합 음성
    merged = engine.merge_audio_files(auds, "full_narration.mp3")
    assert merged, "음성 병합 실패"

    # 3) 이미지 3개
    imgs = sorted(glob.glob("output/images/scene_0*.png"))[:3]
    assert len(imgs) == 3, f"이미지 부족: {imgs}"

    # 4) 영상 생성 (자막 + 인코더 자동 선택)
    ed = VideoEditor()
    durs = ed.measure_scene_durations(auds, len(imgs), merged)
    print("장면 시간:", durs)
    out = ed.create_video_from_images(imgs, merged, output_file="_sub_test.mp4",
                                      scene_durations=durs, scene_texts=TEXTS)
    assert out, "영상 생성 실패"
    ass = os.path.join("output", "subtitles.ass")
    print(f"ASS 존재: {os.path.exists(ass)} / 크기: {os.path.getsize(ass) if os.path.exists(ass) else 0}")
    print(f"영상 길이: {ed.probe_duration(out):.2f}s (음성 {ed.probe_duration(merged):.2f}s)")

    # 5) 자막 확인용 프레임 추출 (1초 지점)
    os.makedirs("output/debug_frames", exist_ok=True)
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "1.0", "-i", out,
                    "-frames:v", "1", "output/debug_frames/sub_test.png"], check=True)
    print("프레임: output/debug_frames/sub_test.png")
    print("TEST OK")
