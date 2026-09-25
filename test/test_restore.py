# -*- coding: utf-8 -*-
"""복구 기능 검증: script.txt 파싱 + titles/description 복구 + 저장 round-trip

주의: round-trip(쓰기) 부분은 **temp 폴더로 격리**해서 실제 output 을 건드리지 않는다.
      (예전에는 output/script.txt 를 직접 덮어써 변경감지 기준까지 오염시켰음 — 2026-09-23)
"""
import sys, io, os, shutil, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import main
from modules import script_store

titles, desc, script = main.restore_saved_files()
print(f"제목 {len(titles)}개: {titles[:2]}")
print(f"설명 {len(desc)}자")
print(f"대본 {len(script)}장면")
for sc in script[:2]:
    print(f"  장면{sc['scene']} ({sc['time']}) 내용: {sc['content'][:30]}... 시각: {sc['visual'][:30]}...")

assert len(titles) >= 1, "제목 복구 실패"
assert len(desc) > 50, "설명 복구 실패"
assert len(script) >= 10, f"대본 장면 수 이상: {len(script)}"
assert all(sc.get("content") and sc.get("visual") for sc in script), "빈 내용/시각 있음"

# round-trip: temp 폴더에서 저장 후 재파싱해도 동일한지 (실제 output 보호)
ROOT = Path(__file__).resolve().parents[1]
tmp = Path(tempfile.mkdtemp(prefix="saas_restore_"))
try:
    script_store.set_output_dir(tmp)
    main.save_script_file(script)
    _, _, script2 = main.restore_saved_files()
    same = [x["content"] for x in script2] == [x["content"] for x in script]
    assert same, "round-trip 불일치"
finally:
    script_store.set_output_dir(ROOT / "output")
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("🎉 복구 기능 검증 통과 (파싱 + round-trip · temp 격리)")
