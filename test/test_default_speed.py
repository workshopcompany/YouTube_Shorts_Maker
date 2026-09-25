"""
기본 배속(1.3x) + 장면 간극 최소화 통합 테스트 (실제 대본 12장면)
흐름: output/script.txt 대본 → Edge TTS 재생성(앞/뒤 무음 트리밍)
      → 병합(config SCENE_GAP_MS 간극) → config 기본 배속으로 영상 제작 → 검증
검증 항목: 문장 사이 정적 / 영상 길이 == 병합음성 ÷ 배속 / 마지막 장면 간극 없음 / 자막 프레임
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

from config import (OUTPUT_DIR, SCENE_GAP_MS, TTS_TAIL_SILENCE_MS,
                    VIDEO_PLAYBACK_SPEED)
from main import parse_script_text
from modules.tts import TTSEngine
from modules.video_edit import VideoEditor


def silence_list(path: str, noise_db: int = -45, min_d: float = 0.1) -> list:
    r = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", path,
         "-af", f"silencedetect=noise={noise_db}dB:d={min_d}", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return [float(m) for m in re.findall(r"silence_duration:\s*([0-9.]+)", r.stderr or "")]


def main():
    out_dir = Path(OUTPUT_DIR)
    script = parse_script_text((out_dir / "script.txt").read_text(encoding="utf-8"))
    print(f"📄 대본 {len(script)}장면 로드 (output/script.txt)")

    imgs = [str(p) for p in sorted((out_dir / "images").glob("scene_*[0-9].png"))]
    imgs = imgs[:len(script)]
    assert len(imgs) == len(script), f"이미지 부족: {len(imgs)}장 / 대본 {len(script)}"
    print(f"🖼️ 이미지 {len(imgs)}장 사용")

    # 1) 음성 재생성 (새 트리밍 적용) + 병합 (새 간극 적용)
    engine = TTSEngine()
    auds = engine.generate_scene_audio(script)
    assert len(auds) == len(script), f"음성 생성 실패: {len(auds)}개"
    merged = engine.merge_audio_files(auds)
    assert merged and os.path.exists(merged), "음성 병합 실패"

    ed = VideoEditor()
    clips = [ed.probe_duration(p) for p in auds]
    merged_d = ed.probe_duration(merged)
    inserted = merged_d - sum(clips)
    expect_insert = (int(SCENE_GAP_MS) / 1000.0) * (len(auds) - 1)
    print(f"\n📊 병합 음성 {merged_d:.2f}초 = 장면합 {sum(clips):.2f}초 + 입 간극 {inserted:.2f}초 "
          f"(기대 {expect_insert:.2f}초)")
    assert abs(inserted - expect_insert) < 0.2, "삽입 간극이 설정값과 불일치"

    sils = [s for s in silence_list(merged) if 0.1 < s < 0.9]
    per_boundary = (sum(sils) / len(sils)) if sils else 0.0
    print(f"   문장 사이 정적 실측: 평균 {per_boundary:.2f}초 "
          f"(꼬리 {TTS_TAIL_SILENCE_MS}ms + 간극 {SCENE_GAP_MS}ms = "
          f"{(TTS_TAIL_SILENCE_MS + SCENE_GAP_MS) / 1000:.2f}초)")
    assert abs(per_boundary - (TTS_TAIL_SILENCE_MS + SCENE_GAP_MS) / 1000.0) < 0.12, \
        f"문장 사이 정적 불일치: {per_boundary:.2f}초"
    saved = (1.4 - per_boundary) * (len(auds) - 1)
    print(f"   (기존 꼬리 0.9초 + 0.5초 무음 → 약 1.4초였음 · 이 영상 기준 약 {saved:.1f}초 단축)")

    # 2) 장면 타이밍 (마지막 장면에는 간극 없음)
    durs = ed.measure_scene_durations(auds, len(imgs), merged)
    assert abs(sum(durs) - merged_d) < 0.1, "장면 합계와 병합 음성 길이 불일치"
    assert abs(durs[-1] - clips[-1]) < 0.05, "마지막 장면에 간극이 더해짐"
    print("\n🎬 장면 타이밍 (음성 → 표시):")
    for i, (c, d) in enumerate(zip(clips, durs), 1):
        print(f"   장면 {i:2d}: {c:.2f}초 → {d:.2f}초")

    # 3) 영상 제작 (config 기본 배속 = 1.3x)
    speed = float(VIDEO_PLAYBACK_SPEED)
    texts = [s.get("content", "") for s in script]
    out = ed.create_video_from_images(
        imgs, merged, output_file=f"default_{speed}x.mp4",
        scene_durations=durs, scene_texts=texts, playback_speed=speed)
    assert out, "영상 생성 실패"

    v_d = ed.probe_duration(out)
    expect_v = merged_d / speed
    print(f"\n🎬 영상 {v_d:.2f}초 (병합 음성 {merged_d:.2f}초 ÷ {speed}x = 기대 {expect_v:.2f}초)")
    assert abs(v_d - expect_v) < 1.0, "배속이 영상에 반영되지 않음"

    # 4) 자막/말풍선 프레임 2장 추출 (2번째, 마지막 장면)
    fr = out_dir / "debug_frames"
    fr.mkdir(parents=True, exist_ok=True)
    t2 = (durs[0] + durs[1] / 2) / speed
    t_last = max(v_d - 1.0, 0)
    for name, t in ((f"default_{speed}x_scene2.png", t2),
                    (f"default_{speed}x_last.png", t_last)):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", out,
                        "-frames:v", "1", str(fr / name)], check=True)
        print(f"   🖼️ {fr / name} (t={t:.1f}초)")

    print(f"\n✅ 기본 {speed}x 테스트 통과 — 문장 사이 정적 {per_boundary:.2f}초, "
          f"영상 {v_d:.2f}초")


if __name__ == "__main__":
    main()