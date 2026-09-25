# -*- coding: utf-8 -*-
"""
④ 영상·업로드 탭 + base 원본 동기화 기능 검증

1. overlay.sync_missing_bases — base 없는 장면을 현재 이미지로 보존
2. overlay.apply_scene — base 없을 때 승격(보호) 후 텍스트 합성
3. pipeline.upload_video — 영상 자동 선택 + 제목(title_index) 선택 (업로드는 fake)
4. pipeline.execute_spec — "upload" 단계 인식 (알 수 없는 단계로 떨어지지 않음)
"""
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="saas_vtab_"))
config.OUTPUT_DIR = str(TMP)

from modules import overlay as ov          # noqa: E402
from modules import pipeline, script_store  # noqa: E402

FAIL = []


def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL"), "-", name, ("| " + detail if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def fake_upload_module(captured):
    """modules.youtube_upload 를 가짜로 꽂아 실제 API 호출을 막는다."""
    mod = types.ModuleType("modules.youtube_upload")

    class FakeUploader:
        def upload_video(self, video_path=None, title="", description="", privacy="private"):
            captured.append({"video_path": video_path, "title": title,
                             "privacy": privacy, "description": description})
            return {"success": True, "url": "https://youtube.com/watch?v=fake",
                    "privacy": privacy}

    mod.YouTubeUploader = FakeUploader
    sys.modules["modules.youtube_upload"] = mod


def main():
    # --- 준비: 대본 1장 + 완성 이미지만 있고 base 는 없는 상태 ---
    script_store.save_script_file([{"time": "0:00", "content": "안녕하세요"}])
    img_dir = TMP / "images"
    (img_dir / "base").mkdir(parents=True)
    from PIL import Image
    Image.new("RGB", (320, 180), (30, 90, 160)).save(img_dir / "scene_01.png")

    # 1) sync_missing_bases — base 없는 장면 보존
    res = ov.sync_missing_bases([{"time": "0:00", "content": "안녕하세요"}])
    check("sync_missing_bases 가 base 승격", res.get("ok") and 1 in res.get("saved", []) and
          (img_dir / "base" / "scene_01.png").exists())

    # 2) apply_scene — base 없는 장면(번호 2)에서도 예외 없이 합성 + 승격
    Image.new("RGB", (320, 180), (160, 80, 40)).save(img_dir / "scene_02.png")
    try:
        out = ov.apply_scene(2, "테스트 문장")
        ok2 = bool(out) and (img_dir / "base" / "scene_02.png").exists()
        detail = f"out={out}"
    except Exception as e:
        ok2, detail = False, repr(e)
    check("apply_scene 이 base 승격 후 합성", ok2, detail)

    # 3) upload_video — 영상 자동 선택 + title_index 선택
    captured = []
    fake_upload_module(captured)
    vd = TMP / "videos"
    vd.mkdir()
    (vd / "my_video.mp4").write_bytes(b"\x00" * 16)
    import main
    main.save_text_files(["제목A", "제목B"], "설명입니다")
    print("DBG loaded =", script_store.load_text_files())
    print("DBG fake module =", sys.modules.get("modules.youtube_upload"))
    print("DBG save_text_files =", main.save_text_files)
    r = pipeline.upload_video(privacy="unlisted", title_index=1, log=lambda *a: None)
    print("DBG r =", r)
    print("DBG captured =", captured)
    ok3 = (r.get("ok") and r.get("title") == "제목B"
           and captured and captured[-1]["title"] == "제목B"
           and captured[-1]["privacy"] == "unlisted")
    check("upload_video 자동선택+title_index", ok3, str(r))

    # 3-2) 영상이 없으면 안내 메시지 (업로드 호출 없이)
    captured.clear()
    r = pipeline.upload_video(video_path=str(TMP / "nope.mp4"), log=lambda *a: None)
    check("upload_video 영상 없음 안내",
          (not r.get("ok")) and "영상" in (r.get("reason") or ""),
          str(r))

    # 4) execute_spec — upload 단계 인식
    captured.clear()
    out = pipeline.execute_spec(
        {"steps": ["upload"], "privacy": "public", "title_index": 0},
        log=lambda *a: None)
    ok4 = out["ok"] and out["steps"].get("upload", {}).get("ok") \
        and "알 수 없는 단계" not in out["log"]
    check("execute_spec upload 단계", ok4, out["log"][-200:])

    import shutil
    shutil.rmtree(TMP, ignore_errors=True)
    print(("ALL OK" if not FAIL else f"FAILED: {FAIL}"))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
