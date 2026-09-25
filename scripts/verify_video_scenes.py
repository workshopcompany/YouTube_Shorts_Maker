# -*- coding: utf-8 -*-
"""완성 영상의 각 구간 프레임이 올바른 장면 이미지와 일치하는지 검증.
방법: 각 장면 중간 시점 프레임을 뽑아, 12개 장면 이미지(cover-crop 리사이즈)와
거리를 비교 → '자기 장면이 최근접'이면 OK. (SDXL 512x1024 기준)"""
import os, subprocess, sys, glob
import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

vids = [p for p in glob.glob("output/videos/*.mp4") if not os.path.basename(p).startswith("_old_")]
assert vids, "완성 영상 없음"
video = vids[0]

dur = float(subprocess.check_output(
    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
     "-of", "default=noprint_wrappers=1:nokey=1", video]).decode().strip())
N = 12
print(f"영상: {video} ({dur:.1f}초, 장면 {N}개, 구간당 {dur/N:.2f}초)")


def cover_1080x1920_small(img, w=32, h=57):
    """이미지를 영상과 동일하게 1080x1920 cover(확대 후 중앙 crop)한 뒤 소형화"""
    iw, ih = img.size
    scale = max(1080 / iw, 1920 / ih)
    nw, nh = round(iw * scale), round(ih * scale)
    r = img.resize((nw, nh))
    left, top = (nw - 1080) // 2, (nh - 1920) // 2
    r = r.crop((left, top, left + 1080, top + 1920))
    return np.asarray(r.convert("L").resize((w, h)), dtype=float)


os.makedirs("output/debug_frames", exist_ok=True)
scene_imgs = {k: cover_1080x1920_small(Image.open(f"output/images/scene_{k:02d}.png"))
              for k in range(1, N + 1)}

# 각 장면의 실제 시작 시각 = 장면별 음성 길이 누적 (영상 편집기가 이 기준으로 이미지 전환)
audio_dir = "output/audio"
starts, cum = [], 0.0
for k in range(1, N + 1):
    starts.append(cum)
    mp3 = os.path.join(audio_dir, f"scene_{k:02d}.mp3")
    d = float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", mp3]).decode().strip())
    cum += d
print(f"음성 기준 전체 길이: {cum:.1f}초 / 영상 길이: {dur:.1f}초")

ok = 0
for k in range(1, N + 1):
    seg_end = starts[k] if k < N else dur  # 마지막 장면은 영상 끝까지
    t = (starts[k - 1] + seg_end) / 2
    if t >= dur:
        t = dur - 0.5
    fp = f"output/debug_frames/v_{k:02d}.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", video,
                    "-frames:v", "1", fp], check=True)
    frame = np.asarray(Image.open(fp).convert("L").resize((32, 57)), dtype=float)
    dists = {j: np.abs(frame - img).mean() for j, img in scene_imgs.items()}
    best = min(dists, key=dists.get)
    mark = "OK " if best == k else "DIFF"
    if best == k:
        ok += 1
    print(f"  [{mark}] t={t:5.1f}s 구간{k:2d}: 최근접=장면{best:2d} "
          f"(자기:{dists[k]:.1f} / 최소:{dists[best]:.1f})")

print(f"\n판정: {ok}/{N} 구간 일치 → {'🎉 성공: 장면별 이미지가 순서대로 들어감' if ok == N else '⚠️ 일부 불일치'}")
sys.exit(0 if ok == N else 1)

