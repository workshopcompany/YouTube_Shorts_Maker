"""
장면 간 무음 간극(쉬는 시간) 검증
- Edge TTS로 테스트 대사 3개 생성 → 앞/뒤 무음 트리밍 → 병합
- 실측 문장 간 정적 = (TTS_TAIL_SILENCE_MS + SCENE_GAP_MS)/1000 초 인지 확인
- 영상 장면 타이밍 배분(measure_scene_durations)도 같은 값으로 정렬되는지 확인
※ 실제 프로젝트 파일(scene_XX.mp3)은 건드리지 않음 (gap_test_* 로만 작업)
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

from config import OUTPUT_DIR, SCENE_GAP_MS, TTS_TAIL_SILENCE_MS
from modules.tts import TTSEngine
from modules.video_edit import VideoEditor

TEST_TEXTS = [
    "안녕하세요, 오늘은 파이썬 자동화를 알아볼게요.",
    "자동화를 쓰면 세 시간 걸리던 일이 십 분이면 끝납니다.",
    "지금 바로 시작해볼까요?",
]


def silence_list(path: str, noise_db: int = -45, min_d: float = 0.1) -> list:
    """silencedetect로 무음 구간 목록(초) 추출"""
    r = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", path,
         "-af", f"silencedetect=noise={noise_db}dB:d={min_d}", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return [float(m) for m in re.findall(r"silence_duration:\s*([0-9.]+)", r.stderr or "")]


def main():
    expect_gap = (int(SCENE_GAP_MS) + int(TTS_TAIL_SILENCE_MS)) / 1000.0
    print(f"⚙️ 설정: 꼬리무음 {TTS_TAIL_SILENCE_MS}ms + 장면 간극 {SCENE_GAP_MS}ms "
          f"= 기대 문장 간 정적 {expect_gap:.2f}초")

    engine = TTSEngine()
    editor = VideoEditor()
    audio_dir = Path(OUTPUT_DIR) / "audio"

    raw_paths, trimmed_paths = [], []
    for i, text in enumerate(TEST_TEXTS, 1):
        raw = str(audio_dir / f"gap_test_raw_{i:02d}.mp3")
        engine.generate_speech_edge(text, raw)
        assert os.path.exists(raw), f"Edge TTS 생성 실패: {raw}"

        trimmed = engine.trim_silence(raw)
        if trimmed != raw and os.path.exists(trimmed):
            os.replace(trimmed, raw)          # generate_scene_audio와 동일하게 교체
        raw_paths.append(raw)
        trimmed_paths.append(raw)

        raw_d = editor.probe_duration(raw)
        sils = silence_list(raw)
        tail_kept = sils[-1] if sils and sils[-1] < 0.6 else 0.0
        print(f"   장면 {i}: 트리밍 후 {raw_d:.2f}초 / 마지막 무음 {tail_kept:.2f}초 "
              f"(무음 구간 {len(sils)}개)")
        assert tail_kept <= 0.30, f"꼬리 무음 과다: {tail_kept:.2f}초"
        assert raw_d > 0.5, f"장면 {i} 음성 길이 이상"

    # 병합 (테스트 전용 파일명 → 실전 파일 보호)
    merged = engine.merge_audio_files(trimmed_paths, output_file="gap_test_full.mp3")
    assert merged and os.path.exists(merged), "병합 실패"

    merged_d = editor.probe_duration(merged)
    clips_sum = sum(editor.probe_duration(p) for p in trimmed_paths)
    inserted = merged_d - clips_sum
    print(f"\n📊 병합 {merged_d:.2f}초 = 장면합 {clips_sum:.2f}초 + 삽입 간극 {inserted:.2f}초")
    print(f"   (기존: 꼬리무음 약 0.9초 + 0.5초 입 = 문장 사이 약 1.4초 정적)")

    sils = silence_list(merged)
    mid = [s for s in sils if 0.1 < s < 0.8]
    per_boundary = (sum(mid) / len(mid)) if mid else 0.0
    print(f"   silencedetect: 문장 사이 정적 {[round(s, 2) for s in mid]} → 평균 {per_boundary:.2f}초")

    # 삽삽입 간극 합 = SCENE_GAP_MS × (장면수-1)
    assert abs(inserted - (int(SCENE_GAP_MS) / 1000.0) * (len(TEST_TEXTS) - 1)) < 0.1, \
        f"삽삽입 간극 불일치: {inserted:.2f}초"
    # 문장 사이 실제 정적 = 꼬리무음 + 삽삽입 간극
    assert abs(per_boundary - expect_gap) < 0.12, \
        f"문장 사이 정적이 설정값과 불일치: {per_boundary:.2f}초 (기대 {expect_gap:.2f}초)"

    # 영상 장면 타이밍 배분 검증
    durs = editor.measure_scene_durations(trimmed_paths, len(TEST_TEXTS), merged)
    print("\n🎬 장면 표시 시간 배분:")
    for i, (p, d) in enumerate(zip(trimmed_paths, durs), 1):
        clip = editor.probe_duration(p)
        print(f"   장면 {i}: 음성 {clip:.2f}초 → 표시 {d:.2f}초 (+{d - clip:.2f}초)")
    assert abs(sum(durs) - merged_d) < 0.1, "장면 합계와 병합 음성 길이 불일치"
    assert abs(durs[-1] - editor.probe_duration(trimmed_paths[-1])) < 0.05, \
        "마지막 장면에 간극이 더해짐 (무음 없어야 함)"

    saved = (1.4 - per_boundary) * (len(TEST_TEXTS) - 1)
    print(f"\n✅ 테스트 통과: 문장 사이 정적 {per_boundary:.2f}초/장면 "
          f"(기존 약 1.4초 → 이 장면수 기준 약 {saved:.1f}초 단축)")


if __name__ == "__main__":
    main()
