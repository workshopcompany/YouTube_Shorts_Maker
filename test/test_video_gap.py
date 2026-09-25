"""영상 생성 '이미지 누락' 회귀 테스트

검증 항목:
1. ensure_scene_images — 대본 길이와 1:1 (누락 장면은 임시 플레이스홀더로 대체)
2. 0바이트 손상 이미지도 누락으로 감지
3. build_video — exists 필터로 인덱스가 밀리지 않는지 (이미지/음성/자막 정렬)
4. 음성 파일이 중간에 없어도 audio_paths 인덱스가 유지되는지 (평균 길이 보정 전제)
"""
import os
import sys
import tempfile
import shutil
import pathlib
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules import script_store                     # noqa: E402
from modules.image_gen import ensure_scene_images    # noqa: E402
from modules import pipeline                         # noqa: E402
from modules.video_edit import VideoEditor           # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"[OK] {name}")
    else:
        print(f"[NG] {name} :: {detail}")
        FAILED.append(name)


def main() -> int:
    TMP = pathlib.Path(tempfile.mkdtemp(prefix="saas_vidgap_"))
    prev_out = script_store.scene_image_path(1).parent.parent  # 현재 output 루트
    script_store.set_output_dir(str(TMP))
    try:
        script = [
            {"scene": 1, "time": "0~5초", "content": "첫 대사", "visual": "첫 묘사"},
            {"scene": 2, "time": "5~10초", "content": "둘째 대사", "visual": "둘째 묘사"},
            {"scene": 3, "time": "10~15초", "content": "셋째 대사", "visual": "셋째 묘사"},
        ]
        img1 = script_store.scene_image_path(1)
        img1.parent.mkdir(parents=True, exist_ok=True)
        from PIL import Image
        Image.new("RGB", (1080, 1920), (10, 120, 30)).save(img1)
        # 3번은 0바이트 손상 파일
        script_store.scene_image_path(3).write_bytes(b"")

        # ---------- [1] 1:1 보장 + 플레이스홀더 대체 ----------
        logs = []
        images, missing = ensure_scene_images(script, log=lambda m="": logs.append(str(m)))
        check("[1-1] 반환 길이 == 대본 길이 (3)", len(images) == 3, f"len={len(images)}")
        check("[1-2] 누락 장면 = [2, 3] (0바이트 포함)", missing == [2, 3], f"missing={missing}")
        check("[1-3] 1번은 실제 이미지 유지", images[0] == str(img1), images[0])
        check("[1-4] 2번은 placeholder 경로", "_placeholder" in images[1] and pathlib.Path(images[1]).exists(),
              images[1])
        check("[1-5] 실제 경로는 그대로 비어있음 (상태 가리기 아님)",
              not script_store.scene_image_path(2).exists())
        check("[1-6] placeholder가 1:1로 고유 파일",
              len(set(images)) == 3, str(images))

        # ---------- [2] 전부 있으면 placeholder 미생성 ----------
        for i in (2, 3):
            Image.new("RGB", (1080, 1920), (80, 10, 10)).save(script_store.scene_image_path(i))
        images2, missing2 = ensure_scene_images(script, log=lambda m="": None)
        check("[2-1] 누락 없으면 missing 비어있음", missing2 == [], str(missing2))
        check("[2-2] 전부 실제 경로", all("_placeholder" not in p for p in images2), str(images2))

        # ---------- [3] build_video 인자 정렬 (이미지 1개 삭제 시나리오) ----------
        script_store.save_script_file(script)
        script_store.scene_image_path(2).unlink()  # 2번만 누락
        script_store.scene_audio_path(2).unlink(missing_ok=True)  # 2번 음성도 없다고 가정

        captured = {}

        def fake_cvi(self, image_paths, audio_path=None, output_file=None,
                     scene_durations=None, scene_texts=None, playback_speed=None):
            captured["images"] = list(image_paths)
            captured["audio"] = audio_path
            captured["durs"] = scene_durations
            captured["texts"] = list(scene_texts or [])
            out = pathlib.Path(output_file)
            vp = (script_store.out_dir() / "videos")
            vp.mkdir(parents=True, exist_ok=True)
            real = vp / out.name
            real.write_bytes(b"fake")
            return str(real)

        def fake_measure(self, audio_paths, n_images, audio_path=None):
            captured["audio_args"] = list(audio_paths)
            captured["n"] = n_images
            return [1.0] * n_images

        with mock.patch.object(VideoEditor, "create_video_from_images", fake_cvi), \
             mock.patch.object(VideoEditor, "measure_scene_durations", fake_measure), \
             mock.patch.object(pipeline, "merge_audio", return_value=None), \
             mock.patch.object(script_store, "mark_video_built", lambda s, p: None):
            vlogs = []
            res = pipeline.build_video(script, titles=["제목"], speed=1.0,
                                       log=lambda m="": vlogs.append(str(m)))

        check("[3-1] 영상 단계 성공", res.get("ok"), str(res))
        check("[3-2] 이미지 목록 길이 == 대본 길이 (누락이 자리를 지킴)",
              len(captured["images"]) == 3, str(captured.get("images")))
        check("[3-3] 2번 자리가 placeholder (2번 실제 이미지 아님)",
              "_placeholder" in captured["images"][1], str(captured.get("images")))
        check("[3-4] 자막 = 대본 전체 길이·순서 정렬",
              captured["texts"] == ["첫 대사", "둘째 대사", "셋째 대사"], str(captured.get("texts")))
        check("[3-5] 음성 인덱스 유지 — 2번 자리에 2번 경로가 그대로 (필터 X)",
              captured["audio_args"][1] == str(script_store.scene_audio_path(2)),
              str(captured.get("audio_args")))
        check("[3-6] measure 호출 n_images == 3", captured.get("n") == 3, str(captured.get("n")))
        check("[3-7] 누락 경고 로그 출력",
              any("이미지 없는 장면" in m for m in vlogs) and any("음성 없는 장면" in m for m in vlogs),
              str(vlogs))

        if FAILED:
            print(f"\n❌ {len(FAILED)}개 실패: {FAILED}")
            return 1
        print("\n✅ 전체 통과 (14개 검사) — 영상 이미지 누락 방지")
        return 0
    finally:
        script_store.set_output_dir(str(prev_out))
        shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
