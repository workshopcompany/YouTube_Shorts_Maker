# -*- coding: utf-8 -*-
"""script.txt ↔ 체크포인트 동기화 + 변경 감지 검증 (API·SD 호출 없음)

사용: .\\venv\\Scripts\\python.exe -X utf8 scripts\\test_script_sync.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from modules import script_store  # noqa: E402


def make_scene(i: int, content: str, visual: str) -> dict:
    return {"scene": i, "time": f"{(i - 1) * 5}~{i * 5}초", "content": content, "visual": visual}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="saas_sync_"))
    script_store.set_output_dir(tmp)
    try:
        # [1] 체크포인트만 있고 script.txt 는 손으로 수정한 상황 재현
        old = [make_scene(i, f"옛 대사 {i}", f"옛 시각 {i}") for i in range(1, 4)]
        script_store.save_checkpoint(1, {
            "idea": "테스트 아이디어",
            "text_result": {"titles": ["원래 제목"], "description": "원래 설명", "script": old},
        })
        new = [
            make_scene(1, "옛 대사 1", "옛 시각 1"),   # 그대로
            make_scene(2, "새 대사 2", "옛 시각 2"),   # 대사만 변경
            make_scene(3, "옛 대사 3", "새 시각 3"),   # 시각만 변경
        ]
        script_store.save_script_file(new)

        report = script_store.sync_script_to_checkpoint(apply=True)
        assert report["changed"] and report["applied"], report
        assert report["diff"]["content_changed"] == [2], report["diff"]
        assert report["diff"]["visual_changed"] == [3], report["diff"]

        ck = script_store.load_checkpoint()
        tr = ck["data"]["text_result"]
        assert [s["content"] for s in tr["script"]] == ["옛 대사 1", "새 대사 2", "옛 대사 3"], tr["script"]
        assert tr["titles"] == ["원래 제목"], "제목이 보존되지 않음"
        print("[1] ✅ script.txt 수정분이 체크포인트에 반영됨 (제목/설명 보존)")

        # [2] 변경 감지 기준(baseline) + 작업 계획
        #     이미지/음성 파일이 이미 있는 상태를 흉내 (파일이 없으면 '생성 필요'로 잡히기 때문)
        for i in (1, 2, 3):
            p = script_store.scene_image_path(i)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"dummy")
            a = script_store.scene_audio_path(i)
            a.parent.mkdir(parents=True, exist_ok=True)
            a.write_bytes(b"dummy")

        st = script_store.load_state()
        assert st.get("img_sig") and st.get("audio_sig"), st
        plan = script_store.plan_tasks(new)
        assert plan["image_regen"] == [3], plan["image_regen"]
        assert plan["image_overlay"] == [2], plan["image_overlay"]
        assert plan["audio_regen"] == [2], plan["audio_regen"]
        assert plan["video_stale"] is True
        print(f"[2] ✅ 변경 감지 → 이미지 재생성 {plan['image_regen']} / 텍스트만 {plan['image_overlay']} / 음성 {plan['audio_regen']}")

        # [3] 이미지·음성·텍스트를 다시 만든 뒤에는 변경분이 사라져야 함
        script_store.mark_assets(new, kinds=("img", "audio"))
        script_store.mark_overlay_applied_map(
            {str(i): script_store.content_hash(f"scene{i}") for i in (1, 2, 3)})
        plan2 = script_store.plan_tasks(new)
        assert plan2["image_regen"] == [] and plan2["image_overlay"] == [] and plan2["audio_regen"] == [], plan2
        print("[3] ✅ 재작업 후에는 변경분 0 (불필요한 재생성 방지)")

        # [4] 장면 추가/삭제 감지
        more = new + [make_scene(4, "추가 대사", "추가 시각")]
        d = script_store.diff_scripts(new, more)
        assert d["added"] == [4] and d["count_changed"], d
        fewer = new[:2]
        d2 = script_store.diff_scripts(new, fewer)
        assert d2["removed"] == [3], d2
        print(f"[4] ✅ 장면 추가 {d['added']} / 삭제 {d2['removed']} 감지")

        # [5] script.txt 저장 ↔ 파싱 round-trip
        txt = script_store.format_script_text(more)
        back = script_store.parse_script_text(txt)
        assert [s["content"] for s in back] == [s["content"] for s in more]
        assert [s["visual"] for s in back] == [s["visual"] for s in more]
        print("[5] ✅ script.txt round-trip 일치")
    finally:
        script_store.set_output_dir(Path(ROOT) / "output")
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    main()
    print("\n🎉 대본-체크포인트 동기화/변경 감지 검증 통과")
