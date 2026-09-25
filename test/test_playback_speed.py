"""
재생 배속 테스트: 1.2배속으로 영상 생성 → 오디오 배속/영상 길이/자막 검증
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

from config import OUTPUT_DIR
from modules.video_edit import VideoEditor


def main():
    # 명령줄 인자로 배속 지정 (기본 1.2): python scripts/test_playback_speed.py 1.5
    speed = float(sys.argv[1]) if len(sys.argv) > 1 else 1.2
    print(f"⚡ 테스트 배속: {speed}x")
    editor = VideoEditor()
    audio_dir = Path(OUTPUT_DIR) / "audio"
    scene_audios = sorted(str(p) for p in audio_dir.glob("scene_*.mp3"))
    full_audio = str(audio_dir / "full_narration.mp3")
    image_paths = sorted(str(p) for p in (Path(OUTPUT_DIR) / "images").glob("scene_*.png"))
    image_paths = image_paths[:len(scene_audios)]

    print(f"이미지: {len(image_paths)}장 / 장면 음성: {len(scene_audios)}개")
    assert len(image_paths) >= 2 and len(scene_audios) >= 2, "테스트 자료 부족"

    durs = editor.measure_scene_durations(scene_audios, len(image_paths), full_audio)
    orig_total = sum(durs)
    print(f"원본 타임라인: {orig_total:.2f}초 (병합 음성 {editor.probe_duration(full_audio):.2f}초)")

    scene_texts = [f"장면 {i + 1} 배속 테스트 자막" for i in range(len(image_paths))]

    # 1) 오디오 배속 단독 검증 (atempo, 피치 유지)
    sped = editor.speedup_audio(full_audio, speed)
    assert sped != full_audio, "오디오 배속 실패"
    d_orig = editor.probe_duration(full_audio)
    d_sped = editor.probe_duration(sped)
    print(f"🎧 오디오 배속: {d_orig:.2f}초 → {d_sped:.2f}초 (기대 {d_orig / speed:.2f}초)")
    assert abs(d_sped - d_orig / speed) < 0.5, "오디오 배속 길이 이상"

    # 2) 영상 생성 (배속 적용)
    out = editor.create_video_from_images(
        image_paths, full_audio, output_file=f"speed_test_x{speed}.mp4",
        scene_durations=durs, scene_texts=scene_texts, playback_speed=speed)
    assert out, "영상 생성 실패"

    d_vid = editor.probe_duration(out)
    print(f"🎬 영상 길이: {d_vid:.2f}초 (원본 {orig_total:.2f}초 → 기대 {orig_total / speed:.2f}초)")
    assert abs(d_vid - orig_total / speed) < 1.0, "영상 배속 미반영"

    # 3) 자막 확인 (마지막 장면 프레임 추출)
    frame = Path(OUTPUT_DIR) / "debug_frames"
    frame.mkdir(parents=True, exist_ok=True)
    frame_path = frame / f"speed_test_x{speed}_frame.png"
    subprocess_ff = ["ffmpeg", "-y", "-ss", str(max(d_vid - 1.5, 0)), "-i", out,
                     "-frames:v", "1", str(frame_path)]
    import subprocess
    subprocess.run(subprocess_ff, capture_output=True)
    print(f"🖼️ 검증 프레임: {frame_path}")

    print(f"\n✅ 배속 테스트 통과 (영상+내레이션+자막 {speed}배속)")


if __name__ == "__main__":
    main()
