# -*- coding: utf-8 -*-
"""장면-음성 동기화 검증: 측정 → 영상 생성 → 프레임 대조"""
import sys, os, subprocess, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
from PIL import Image
import main
from modules.video_edit import VideoEditor

_, _, script = main.restore_saved_files()
print(f"대본 복구: {len(script)}장면")
main.clean_stale_scenes(len(script))  # 이전 실행 잔여 장면 파일 제거
editor = VideoEditor()

audio_paths = sorted(glob.glob("output/audio/scene_*.mp3"))
print(f"장면 음성: {len(audio_paths)}개")
assert len(audio_paths) == len(script), f"음성 {len(audio_paths)}개 != 대본 {len(script)}장면 — 잔여 파일 확인 필요"

merged = "output/audio/full_narration.mp3"
durs = editor.measure_scene_durations(audio_paths, len(audio_paths), merged)
print("장면별 표시 시간:", durs)
assert durs and all(d > 0.5 for d in durs), "측정 실패"

total_audio = editor.probe_duration(merged)
total_video = sum(durs)
print(f"영상 합계: {total_video:.2f}s / 병합 음성: {total_audio:.2f}s")
assert abs(total_video - max(total_audio, total_video)) < 0.3, "합계-음성 불일치"

images = [f"output/images/scene_{i:02d}.png" for i in range(1, len(durs) + 1)]
out = editor.create_video_from_images(images, merged,
                                      output_file="sync_test.mp4", scene_durations=durs)
assert out, "영상 생성 실패"

vdur = editor.probe_duration(out)
print(f"영상 길이: {vdur:.2f}s (음성 {total_audio:.2f}s)")
assert abs(vdur - max(total_audio, total_video)) < 1.5, "영상-음성 길이 불일치"

# 프레임 대조: 각 장면 중간 시점의 하단 밴드가 해당 장면 이미지와 일치하는지
os.makedirs("output/debug_frames", exist_ok=True)
def band(a):
    return a[1400:1900]

bounds = [0.0]
for d in durs:
    bounds.append(bounds[-1] + d)

checks = [1, 4, 7, 11]
ok_count = 0
for sn in checks:
    t = (bounds[sn - 1] + bounds[sn]) / 2  # 장면 중간 시점
    frame = f"output/debug_frames/sync_{sn}.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", out,
                    "-frames:v", "1", frame], check=True)
    fb = band(np.array(Image.open(frame).convert("RGB")).astype(float))
    d_ok = np.abs(fb - band(np.array(Image.open(images[sn - 1]).convert("RGB")).astype(float))).mean()
    d_wrong = np.abs(fb - band(np.array(Image.open(images[0]).convert("RGB")).astype(float))).mean()
    hit = d_ok < 10 and (sn == 1 or d_wrong > 10)
    ok_count += hit
    print(f"장면{sn:02d} @ {t:5.2f}s: 정답차 {d_ok:5.2f} / scene_01차 {d_wrong:5.2f} → {'✅' if hit else '❌'}")

os.remove(out)  # 테스트 영상 정리 (나중에 '기존 영상 재활용'이 잘못 집지 않게)
assert ok_count == len(checks), f"프레임-장면 불일치 ({ok_count}/{len(checks)})"
print(f"\n🎉 장면-음성 동기화 검증 통과 ({ok_count}/{len(checks)} 장면 일치)")
