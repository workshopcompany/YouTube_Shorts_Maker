# -*- coding: utf-8 -*-
"""저장된 대본 기준으로 진짜 이미지 재생성 (gemini 또는 sd_local)
사용법: python scripts/regen_images.py [gemini|sd_local] [장면번호...]
장면번호를 주면 해당 장면만, 없으면 전체.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import main
from modules.image_gen import ImageGenerator
from config import SD_LOCAL_CHECKPOINT

mode = sys.argv[1] if len(sys.argv) > 1 else "gemini"
only = [int(x) for x in sys.argv[2:] if x.isdigit()]

titles, desc, script = main.restore_saved_files()
print(f"대본 복구: {len(script)}장면 / 모드: {mode}")
if only:
    script = [sc for sc in script if sc["scene"] in only]
    print(f"대상 장면: {[sc['scene'] for sc in script]}")

if mode == "sd_local":
    img_gen = ImageGenerator(mode="sd_local", local_model_path=SD_LOCAL_CHECKPOINT)
else:
    img_gen = ImageGenerator(mode=mode)

# 장면별 개별 호출 (장면 번호 그대로 파일명 유지: scene_NN.png)
paths = []
for sc in script:
    out = img_gen.generate_scene_images([sc], start_index=sc["scene"])
    paths.extend(out)
print(f"\n완료: {len(paths)}/{len(script)} 장 생성")
for p in paths:
    kb = os.path.getsize(p) // 1024
    print(f"  {p} ({kb}KB)")
