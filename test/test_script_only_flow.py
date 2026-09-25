# -*- coding: utf-8 -*-
"""script.txt 수정 → 체크포인트 동기화 → 변경분만 제작 흐름 검증 (CLI 5번 메뉴)

무거운 단계(이미지 생성/음성/영상)는 스텁으로 바꾸고,
임시 폴더를 작업 폴더로 사용해 실제 파일을 건드리지 않는다.

사용: .\\venv\\Scripts\\python.exe -X utf8 scripts\\test_script_only_flow.py
"""
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="saas_flow_"))
os.chdir(TMP)                      # output/ 이 임시 폴더에 생성되도록
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import main                      # noqa: E402
from modules import script_store, pipeline  # noqa: E402


def scene(i, content, visual):
    return {"scene": i, "time": f"{(i - 1) * 5}~{i * 5}초", "content": content, "visual": visual}


def main_test() -> int:
    # 이전 작업(체크포인트)과 손으로 고친 script.txt 를 준비
    old = [scene(1, "옛 대사 1", "옛 시각 1"),
           scene(2, "옛 대사 2", "옛 시각 2"),
           scene(3, "옛 대사 3", "옛 시각 3")]
    script_store.save_checkpoint(1, {"idea": "테스트",
                                     "text_result": {"titles": ["테스트 제목"],
                                                     "description": "테스트 설명",
                                                     "script": old}})
    new = [scene(1, "옛 대사 1", "옛 시각 1"),   # 그대로
           scene(2, "새 대사 2", "옛 시각 2"),   # 대사만 변경
           scene(3, "옛 대사 3", "새 시각 3")]   # 시각 변경
    script_store.save_script_file(new)

    # 이미지/음성 파일이 이미 있는 상태로 가정
    for i in (1, 2, 3):
        for p in (script_store.scene_image_path(i), script_store.scene_audio_path(i)):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"dummy")

    # ---- [1] 시작 시 자동 동기화 (main_flow 가 하는 일) ----
    report = script_store.sync_script_to_checkpoint(apply=True)
    ck = script_store.load_checkpoint()
    assert report["applied"] and ck["data"]["text_result"]["script"][1]["content"] == "새 대사 2"
    assert ck["data"]["text_result"]["titles"] == ["테스트 제목"]
    print("[1] ✅ script.txt 수정분이 체크포인트에 자동 반영")

    # ---- [2] 무거운 단계 스텁 처리 ----
    calls = {}

    def fake_overlay(script, indices=None, cfg=None, log=print):
        calls["overlay"] = list(indices or [])
        return {"ok": True, "count": len(calls["overlay"])}

    def fake_audio(script, indices=None, log=print):
        calls["audio"] = list(indices or [])
        return {"ok": True, "done": calls["audio"], "failed": []}

    def fake_merge(script=None, log=print):
        calls["merge"] = True
        return ""

    def fake_video(script=None, titles=None, speed=None, log=print):
        calls["video_speed"] = speed
        return {"ok": True, "path": str(Path("output") / "videos" / "stub.mp4")}

    pipeline.render_overlays = fake_overlay
    pipeline.generate_audio = fake_audio
    pipeline.merge_audio = fake_merge
    pipeline.build_video = fake_video

    # ---- [3] 5번 메뉴 흐름 실행 (이미지 건너뛰기 → 음성 건너뛰기 → 영상 만들기) ----
    answers = ["4", "3", "1", ""]     # 이미지: 건너뛰기 / 음성: 건너뛰기 / 영상: 예 / 배속: 기본
    sys.stdin = io.StringIO("\n".join(answers) + "\n")
    ok = main._script_only_flow(new, ["테스트 제목"], "테스트 설명", "테스트", {
        "titles": ["테스트 제목"], "description": "테스트 설명", "script": new})
    assert ok is True, "제작 흐름이 중단됨"
    assert calls["overlay"] == [2], f"텍스트만 다시 그릴 대상이 잘못됨: {calls.get('overlay')}"
    assert calls.get("audio") in (None, []), f"음성 대상이 잘못됨: {calls.get('audio')}"
    assert calls.get("video_speed") == 1.3, calls.get("video_speed")
    print(f"[3] ✅ 변경분만 실행: 텍스트만 {calls['overlay']} / 음성 건너뜀 / 영상 생성(배속 {calls['video_speed']})")

    # ---- [4] 체크포인트가 단계 4(영상까지)로 갱신 ----
    ck2 = script_store.load_checkpoint()
    assert ck2["step"] == 4 and ck2["data"].get("video_path"), ck2
    print(f"[4] ✅ 체크포인트 단계 4로 갱신 (업로드 단계로 연결 가능)")

    # ---- [5] 이미지까지 재생성하는 경우: 대상 장면만 호출되는지 ----
    calls.clear()
    gen = {}

    def fake_images(script, indices=None, mode_key="sd_gguf", cfg=None, clear_stale=True, log=print):
        gen["indices"] = list(indices or [])
        gen["mode"] = mode_key
        return {"ok": True, "done": list(indices or []), "failed": []}

    pipeline.generate_images = fake_images
    script_store.mark_assets(new, kinds=("img",))          # 이미지 최신 상태로 초기화
    script_store.mark_assets(new, kinds=("audio",))
    script_store.mark_overlay_applied_map({str(i): script_store.content_hash(f"k{i}") for i in (1, 2, 3)})
    # 장면 3의 시각을 다시 바꿔 '변경분' 만들기
    new[2]["visual"] = "또 바뀐 시각 3"
    script_store.save_script_file(new)
    script_store.sync_script_to_checkpoint(apply=True)
    sys.stdin = io.StringIO("1\n1\n1\n\n")   # 이미지: 로컬 SD / 음성: 변경분만 / 영상: 예 / 배속 기본
    assert main._script_only_flow(new, ["테스트 제목"], "", "테스트",
                                  {"titles": ["테스트 제목"], "description": "", "script": new}) is True
    assert gen["indices"] == [3], gen
    assert gen["mode"] == "sd_gguf", gen
    print("[5] ✅ 시각이 바뀐 장면만 이미지 재생성 대상으로 전달 (로컬 SD, API 없음)")
    return 0


if __name__ == "__main__":
    try:
        main_test()
        print("\n🎉 script.txt 기반 무API 제작 흐름 검증 통과")
    finally:
        os.chdir(ROOT)
        shutil.rmtree(TMP, ignore_errors=True)
