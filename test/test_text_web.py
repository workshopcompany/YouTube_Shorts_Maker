# -*- coding: utf-8 -*-
"""웹 AI 대본 생성(execute_spec 'text' 단계) 검증 — 실제 API 호출 없이 mock 사용

검증:
  ① generate_text_content: 제목/설명/대본 생성 → script.txt + 체크포인트(step 1)
  ② execute_spec(steps=['text']): 새 대본 생성 후 정상 반환
  ③ script.txt 가 비어 있어도 text 단계면 진행 (오류 아님)
  ④ text 단계 없이 빈 script.txt → 기존처럼 실패 안내
  ⑤ 아이디어 미입력 → 친절한 실패

사용: .\\venv\\Scripts\\python.exe -X utf8 test\\test_text_web.py
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

from modules import pipeline, script_store, overlay  # noqa: E402

FAILED = []


def check(name: str, cond: bool, extra: str = ""):
    print(("[OK] " if cond else "[FAIL] ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILED.append(name)


class FakeTextGen:
    """TextGenerator 대체 — API 호출 없음"""
    def generate_title(self, idea):
        return ["테스트 제목 하나", "테스트 제목 둘"]

    def generate_description(self, idea):
        return "테스트 설명문입니다. 구독과 좋아요를 눌러주세요. " * 3

    def generate_script(self, idea, title_context=None, character=None):
        return [{"scene": i, "time": f"{5 * (i - 1)}~{5 * i}초",
                 "content": f"장면 {i}번 대사입니다", "visual": f"장면 {i}번 묘사"}
                for i in range(1, 4)]

    def fill_empty_scenes(self, idea, script, title_context=None, character=None):
        out = []
        for i, sc in enumerate(script, 1):
            d = dict(sc)
            if not (d.get("content") or "").strip():
                d["content"] = f"채워진 대사 {i}"
            if not (d.get("visual") or "").strip():
                d["visual"] = f"채워진 묘사 {i}"
            out.append(d)
        return out

    def regenerate_scene(self, idea, script, scene_no, title_context=None, character=None):
        out = [dict(sc) for sc in script]
        idx = int(scene_no) - 1
        if 0 <= idx < len(out):
            out[idx]["content"] = "다시 쓴 대사"
            out[idx]["visual"] = "다시 쓴 묘사"
        return out


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="saas_textgen_"))
    script_store.set_output_dir(tmp)
    overlay.OUTPUT_DIR = str(tmp)
    pipeline.make_text_generator = lambda api, gm=None: (FakeTextGen(), "gemini")
    pipeline.OUTPUT_DIR = str(tmp)        # pipeline.save_text_files 등이 temp 를 쓰도록
    try:
        # ---------- [1] generate_text_content ----------
        res = pipeline.generate_text_content("테스트 아이디어", log=lambda m="": None)
        check("[1-1] 대본 생성 성공", res.get("ok") and res.get("count") == 3, str(res))
        st = script_store.load_script_file()
        check("[1-2] script.txt 3장면 저장", len(st) == 3, str(len(st)))
        titles, desc = script_store.load_text_files()
        check("[1-3] 제목/설명 저장", len(titles) == 2 and len(desc) > 10, str(titles))
        ck = script_store.load_checkpoint() or {}
        check("[1-4] 체크포인트 step 1", ck.get("step") == 1, str(ck.get("step")))
        tr = (ck.get("data") or {}).get("text_result") or {}
        check("[1-5] 체크포인트에 대본 포함", len(tr.get("script") or []) == 3)

        # ---------- [2] execute_spec text 단계 ----------
        res2 = pipeline.execute_spec({"steps": ["text"], "idea": "두 번째 아이디어"},
                                     log=lambda m="": None)
        check("[2-1] execute_spec 성공", res2.get("ok"), str(res2)[:200])
        check("[2-2] steps.text 결과 보고", (res2["steps"].get("text") or {}).get("ok"))

        # ---------- [3] 빈 script.txt + text 단계 ----------
        script_store.save_script_file([])
        res3 = pipeline.execute_spec({"steps": ["text"], "idea": "빈 대본에서 생성"},
                                     log=lambda m="": None)
        check("[3-1] 빈 대본에서도 text 단계 진행", res3.get("ok"), str(res3)[:200])

        # ---------- [4] 빈 script.txt + text 없음 → 기존 실패 동작 ----------
        script_store.save_script_file([])
        res4 = pipeline.execute_spec({"steps": ["video"]}, log=lambda m="": None)
        check("[4-1] text 없으면 기존처럼 안내 실패", not res4.get("ok") and res4.get("reason"),
              str(res4)[:200])

        # ---------- [5] 아이디어 미입력 ----------
        res5 = pipeline.generate_text_content("", log=lambda m="": None)
        check("[5-1] 아이디어 없으면 실패 안내", not res5.get("ok") and "아이디어" in (res5.get("reason") or ""),
              str(res5))

        # ---------- [6] 빈 문구 채우기(fill) / 장면 재작성(scene) ----------
        script_store.save_script_file([
            {"scene": 1, "time": "0~5초", "content": "정상 대사", "visual": "정상 묘사"},
            {"scene": 2, "time": "5~10초", "content": "", "visual": ""},
        ])
        res6 = pipeline.generate_text_content("", mode="fill", log=lambda m="": None)
        st6 = script_store.load_script_file()
        check("[6-1] fill: 빈 문구 채워짐",
              res6.get("ok") and st6[1].get("content") == "채워진 대사 2" and st6[1].get("visual") == "채워진 묘사 2",
              str(st6))

        res7 = pipeline.generate_text_content("", mode="scene", scene_index=1, log=lambda m="": None)
        st7 = script_store.load_script_file()
        check("[6-2] scene: 지정 장면 다시 작성",
              res7.get("ok") and st7[0].get("content") == "다시 쓴 대사", str(st7))

        res8 = pipeline.generate_text_content("", mode="scene", scene_index=99, log=lambda m="": None)
        check("[6-3] scene: 범위 밖 번호 → 안내 실패", not res8.get("ok") and "범위" in (res8.get("reason") or ""),
              str(res8))

        # ---------- [7] 한자 감지 / 빈 장면 보존 ----------
        check("[7-1] 한자 포함 감지", script_store.has_hanja("퇴근前要 확인"))
        check("[7-2] 순한글은 통과", not script_store.has_hanja("퇴근 전에 확인해요"))

        # 빈 장면이 저장→로드 왕복에서 보존되는지 (2026-09-23 버그 수정 고정)
        script_store.save_script_file([
            {"scene": 1, "time": "0~5초", "content": "대사", "visual": "묘사"},
            {"scene": 2, "time": "5~10초", "content": "", "visual": ""},
            {"scene": 3, "time": "10~15초", "content": "대사3", "visual": "묘사3"},
        ])
        st9 = script_store.load_script_file()
        check("[7-3] 빈 장면 저장/로드 보존 (3장면 유지)", len(st9) == 3, f"{len(st9)}장면")
        check("[7-4] 중간 빈 장면 위치 유지",
              bool(st9) and not (st9[1].get("content") or st9[1].get("visual")), str(st9[1] if st9 else None))

        print()
        if FAILED:
            print(f"❌ 실패 {len(FAILED)}건: {FAILED}")
            return 1
        print("✅ 전체 통과 (18개 검사) — 웹 AI 대본 생성·보조")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
