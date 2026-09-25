"""장면 간 무음 간극 — 실제 영상 생성 통합 검증
- 테스트 전용 오디오(gap_test_*)만 사용 → 실전 파일(scene_XX.mp3, full_narration.mp3) 보호
- 영상 길이 == 병합 음성 길이(무음 없는 마지막 장면 포함) 인지 확인
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

from config import OUTPUT_DIR, SCENE_GAP_MS, VIDEO_PLAYBACK_SPEED
from modules.tts import TTSEngine
from modules.video_edit import VideoEditor

TEXTS = [
    "안녕하세요, 오늘은 파이썬 자동화를 알아볼게요.",
    "자동화를 쓰면 세 시간 걸리던 일이 십 분이면 끝납니다.",
    "지금 바로 시작해볼까요?",
]


def main():
    engine = TTSEngine()
    editor = VideoEditor()
    audio_dir = Path(OUTPUT_DIR) / "audio"

    # 1) 간극 적용 음성 3개 (테스트 전용 파일명)
    auds = []
    for i, text in enumerate(TEXTS, 1):
        p = str(audio_dir / f"gap_test_raw_{i:02d}.mp3")
        engine.generate_speech_edge(text, p)
        trimmed = engine.trim_silence(p)
        if trimmed != p and os.path.exists(trimmed):
            os.replace(trimmed, p)
        auds.append(p)
    merged = engine.merge_audio_files(auds, output_file="gap_test_full.mp3")
    assert merged, "병합 실패"

    # 2) 이미지 3장
    imgs = sorted(str(p) for p in (Path(OUTPUT_DIR) / "images").glob("scene_*.png"))[:3]
    assert len(imgs) == 3, f"이미지 부족: {imgs}"

    # 3) 영상 생성 (간극 검증이 목적이므로 배속 1.0으로 고정)
    durs = editor.measure_scene_durations(auds, len(imgs), merged)
    print(f"장면 시간: {durs}")
    out = editor.create_video_from_images(imgs, merged, output_file="_gap_test.mp4",
                                         scene_durations=durs, scene_texts=TEXTS,
                                         playback_speed=1.0)
    assert out, "영상 생성 실패"

    d_vid = editor.probe_duration(out)
    d_aud = editor.probe_duration(merged)
    print(f"영상 {d_vid:.2f}초 / 음성 {d_aud:.2f}초 (간극 {SCENE_GAP_MS}ms, 배속 1.0x 고정)")
    assert abs(d_vid - d_aud) < 0.5, "영상과 음성 길이 불일치 (간극 정렬 실패)"

    # 4) 2번째 장면 시작 부근(경계 직후) 프레임 추출 → 말풍선/자막 동기 확인용
    boundary = durs[0]
    frame = Path(OUTPUT_DIR) / "debug_frames" / "gap_test_boundary.png"
    frame.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{boundary + 0.2:.2f}",
                    "-i", out, "-frames:v", "1", str(frame)], check=True)
    print(f"경계 프레임: {frame}")
    print("TEST OK")


if __name__ == "__main__":
    main()
