# -*- coding: utf-8 -*-
"""제목/설명 수정분이 상태 저장·영상 생성·업로드에 반영되는지 검증

배경 버그:
  1) 웹 헤더 "💾 상태 저장"(/api/save_state)이 제목/설명을 저장하지 않아
     수정분이 다음 loadState에서 옛 값으로 덮어씌워짐
  2) buildVideoNow/uploadVideoNow/startBuild 가 saveScript(true) → loadState →
     renderVideoPanel 순으로 input 을 "서버 옛값"으로 되돌린 뒤 spec 을 읽어
     영상 파일명/유튜브 업로드에 옛 제목이 들어감

검사 항목:
  [1] save_checkpoint_state(titles, description) → 제목/설명 파일 갱신
  [2] 제목 미전달 시 기존 파일 불변 (기존 상태저장 동작 유지)
  [3] save_script(+titles/description) 기존 동작 유지
  [4] webapp 핸들러가 /api/save_state 에서 body 의 titles/description 전달
  [5] JS — currentTitleDesc 존재 / saveStateFile 이 제목 포함 전달
  [6] JS — buildVideoNow/uploadVideoNow/startBuild 가 제목을 saveScript "전에" 확보
  [7] JS — saveScript extra 파라미터 + spec override 존재
  [8] JS 문법 (node --check, node 없으면 skip)
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402

# 실제 output 보호 — 임시 폴더를 output 으로 고정한 뒤 모듈을 임포트
TMP = Path(tempfile.mkdtemp(prefix="saas_title_"))
config.OUTPUT_DIR = str(TMP)

from modules import overlay as ov  # noqa: E402
from modules import pipeline, script_store  # noqa: E402

ov.OUTPUT_DIR = str(TMP)
script_store.set_output_dir(TMP)

import webapp  # noqa: E402

FAIL = []


def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL"), "-", name, ("| " + detail if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def reset_out(title="기존 제목", desc="기존 설명"):
    """output 파일들을 초기 상태로"""
    for f in ("titles.txt", "title.txt", "description.txt", "checkpoint.json"):
        p = TMP / f
        if p.exists():
            p.unlink()
    pipeline.save_text_files([title], desc)
    (TMP / "script.txt").write_text(
        "[장면 1] 0~5초\n  내용: 내용 하나\n  시각: 시각 하나\n\n"
        "[장면 2] 5~10초\n  내용: 내용 둘\n  시각: 시각 둘\n",
        encoding="utf-8")


def read(name):
    p = TMP / name
    return p.read_text(encoding="utf-8") if p.exists() else None


def main() -> int:
    # ------------------------------------------------------------
    # [1] 상태 저장 + 제목/설명 → 파일 갱신
    # ------------------------------------------------------------
    reset_out()
    res = webapp.save_checkpoint_state(titles=["수정된 새 제목"],
                                       description="수정된 새 설명")
    check("[1-1] save_checkpoint_state ok", bool(res.get("ok")), str(res))
    check("[1-2] title.txt 갱신", read("title.txt") == "수정된 새 제목",
          repr(read("title.txt")))
    check("[1-3] titles.txt 갱신", (read("titles.txt") or "").find("수정된 새 제목") >= 0,
          repr(read("titles.txt")))
    check("[1-4] description.txt 갱신", read("description.txt") == "수정된 새 설명",
          repr(read("description.txt")))
    check("[1-5] 응답에 titles_saved=True", res.get("titles_saved") is True, str(res))
    check("[1-6] 메시지에 제목·설명 안내 포함", "제목·설명" in (res.get("message") or ""),
          str(res.get("message")))
    ck = script_store.load_checkpoint() or {}
    check("[1-7] 체크포인트 step>=3 저장", int(ck.get("step") or 0) >= 3, str(ck.get("step")))

    # ------------------------------------------------------------
    # [2] 제목 미전달 시 기존 파일 불변 (구식 /api/save_state 호출)
    # ------------------------------------------------------------
    reset_out("그대로 제목", "그대로 설명")
    res2 = webapp.save_checkpoint_state()
    check("[2-1] 구식 호출도 ok", bool(res2.get("ok")), str(res2))
    check("[2-2] title.txt 불변", read("title.txt") == "그대로 제목", repr(read("title.txt")))
    check("[2-3] description.txt 불변", read("description.txt") == "그대로 설명",
          repr(read("description.txt")))
    check("[2-4] titles_saved=False", res2.get("titles_saved") is False, str(res2))

    # ------------------------------------------------------------
    # [3] save_script (대본 저장 + 제목/설명) 기존 동작 유지
    # ------------------------------------------------------------
    reset_out()
    scenes = [{"time": "0~5초", "content": "새 내용", "visual": "새 시각"}]
    r3 = webapp.save_script(scenes, sync=False, titles=["save_script 제목"],
                            description="save_script 설명")
    check("[3-1] save_script ok", bool(r3.get("ok")), str(r3))
    check("[3-2] 제목 저장", read("title.txt") == "save_script 제목", repr(read("title.txt")))
    r4 = webapp.save_script(scenes, sync=False)
    check("[3-3] 제목 없는 save_script ok", bool(r4.get("ok")), str(r4))
    check("[3-4] 제목/설명 미전달 시 불변", read("title.txt") == "save_script 제목"
          and read("description.txt") == "save_script 설명",
          f"{read('title.txt')!r} / {read('description.txt')!r}")

    # ------------------------------------------------------------
    # [4] 핸들러가 /api/save_state 에서 body 전달
    # ------------------------------------------------------------
    src = (ROOT / "webapp.py").read_text(encoding="utf-8")
    check("[4-1] 핸들러 titles/description 전달",
          re.search(r'/api/save_state[\s\S]{0,200}?save_checkpoint_state\(\s*'
                    r'titles=data\.get\("titles"\)\s*,\s*'
                    r'description=data\.get\("description"\)', src) is not None)

    # ------------------------------------------------------------
    # [5][6][7] JS 흐름 회귀 (소스 정적 검사)
    # ------------------------------------------------------------
    html = (ROOT / "webui" / "index.html").read_text(encoding="utf-8")
    check("[5-1] currentTitleDesc 정의", "function currentTitleDesc()" in html)
    check("[5-2] saveStateFile 이 제목 포함 전달",
          re.search(r"function saveStateFile\(\)[\s\S]{0,600}?body\.titles\s*=\s*td\.titles",
                    html) is not None)
    for fn in ("buildVideoNow", "uploadVideoNow", "startBuild"):
        m = re.search(r"function " + fn + r"\([^)]*\)([\s\S]*?)\n\}", html)
        body = m.group(1) if m else ""
        i_td = body.find("currentTitleDesc()")
        # 주석의 "saveScript(..." 문자열 오판 방지를 위해 실제 호출(await saveScript)로 검사
        i_save = body.find("await saveScript(")
        check(f"[6] {fn}: 제목 확보가 saveScript 보다 앞섬",
              bool(body) and 0 <= i_td < i_save, f"td={i_td} save={i_save}")
    check("[7-1] saveScript extra 파라미터", "async function saveScript(silent, extra)" in html)
    check("[7-2] saveScript extra 전송", "body.titles = extra.titles" in html)
    check("[7-3] spec override 존재", html.count("spec.titles = td.titles") >= 2)

    # ------------------------------------------------------------
    # [8] JS 문법 (node --check)
    # ------------------------------------------------------------
    node = shutil.which("node")
    if node:
        scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
        jsf = TMP / "extracted.js"
        jsf.write_text("\n;\n".join(scripts), encoding="utf-8")
        p = subprocess.run([node, "--check", str(jsf)],
                           capture_output=True, text=True, encoding="utf-8")
        check("[8-1] JS 문법 node --check", p.returncode == 0, (p.stderr or "")[:500])
    else:
        print("SKIP - node 없음 (JS 문법 검사 생략)")

    # ------------------------------------------------------------
    print("-" * 60)
    if FAIL:
        print(f"FAIL {len(FAIL)}:", FAIL)
        return 1
    print("ALL CHECKS PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(TMP, ignore_errors=True)

