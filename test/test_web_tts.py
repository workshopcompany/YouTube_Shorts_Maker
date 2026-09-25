# -*- coding: utf-8 -*-
"""웹 편집기 음성 즉시 재생성(/api/tts) 검증 — 실제 네트워크 호출 없이 모의 TTS 사용

사용: .\\venv\\Scripts\\python.exe -X utf8 test\\test_web_tts.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from modules import script_store, pipeline          # noqa: E402
from modules import overlay as overlay_mod          # noqa: E402
import modules.tts as tts_mod                       # noqa: E402
import webapp                                       # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="saas_tts_"))
script_store.set_output_dir(str(TMP))


class FakeTTS:
    """네트워크 없이 즉시 파일을 만드는 모의 TTS"""
    def generate_speech_groq(self, text, out_file):
        Path(out_file).write_bytes(b"FAKE_MP3")
        return out_file

    def trim_silence(self, path):
        return path

    def merge_audio_files(self, paths):
        out = TMP / "audio" / "full_narration.mp3"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"FAKE_MERGED")
        return str(out)


tts_mod.TTSEngine = FakeTTS                      # pipeline 이 함수 안에서 import → 패치 적용됨

SCRIPT = [
    {"scene": 1, "time": "0~5초", "content": "테스트 대사 1", "visual": "묘사 1"},
    {"scene": 2, "time": "5~10초", "content": "테스트 대사 2", "visual": "묘사 2"},
]


def _prep_fresh():
    """모든 자산이 '최신'인 상태(기준 서명 갱신 + 음성 파일 존재)를 만든다."""
    script_store.save_script_file([dict(s) for s in SCRIPT])
    script_store.mark_assets(script_store.load_script_file(), kinds=("img", "audio"))
    (TMP / "audio").mkdir(parents=True, exist_ok=True)
    for i in (1, 2):
        Path(script_store.scene_audio_path(i)).write_bytes(b"FAKE_MP3")


def main() -> int:
    # [1] 명시 지정은 '강제 재생성' — 최신이어도 다시 만든다 (버튼 의도와 일치)
    _prep_fresh()
    r = webapp.regen_audio([1], auto=False)
    assert r.get("ok") and r.get("done") == [1] and r.get("merged"), f"[1] 실패: {r}"
    print("[1] ✅ 명시 지정 → 강제 재생성 + 병합 갱신")

    # [1-2] auto 모드에서 변경분이 없으면 → skipped (불필요한 TTS 호출 없음)
    _prep_fresh()
    r = webapp.regen_audio(None, auto=True)
    assert r.get("ok") and r.get("skipped"), f"[1-2] 실패: {r}"
    print("[1-2] ✅ auto 모드 + 변경 없음 → skipped (네트워크 호출 없음)")

    # [2] 대본 수정 → 변경 감지로 audio_regen 계산
    script = script_store.load_script_file()
    script[1]["content"] = "바뀐 대사 2"
    script_store.save_script_file(script)
    plan = script_store.plan_tasks(script, overlay_key=overlay_mod.current_key)
    assert plan["audio_regen"] == [2], f"[2] 실패: {plan['audio_regen']}"
    print("[2] ✅ 대사 변경 감지: audio_regen =", plan["audio_regen"])

    # [3] 즉시 재생성 → 파일 생성 + 병합 갱신 + 기준 갱신
    r = webapp.regen_audio([2], auto=False)
    assert r.get("ok") and r.get("done") == [2] and r.get("merged"), f"[3] 실패: {r}"
    assert Path(script_store.scene_audio_path(2)).exists()
    assert Path(TMP / "audio" / "full_narration.mp3").exists()
    after = script_store.plan_tasks(script_store.load_script_file(),
                                    overlay_key=overlay_mod.current_key)
    assert after["audio_regen"] == [], f"[3] 기준 미갱신: {after['audio_regen']}"
    print("[3] ✅ 재생성 + 병합 갱신 + 변경 기준 갱신 완료")

    # [4] auto(변경분 전체) 모드 → 이제 할 일 없음 → skipped
    r = webapp.regen_audio(None, auto=True)
    assert r.get("skipped"), f"[4] 실패: {r}"
    print("[4] ✅ auto 모드 skipped")

    # [5] script.txt 없음 → 에러 반환
    saved = script_store.out_dir() / "script.txt"
    bak = saved.with_suffix(".bak_t")
    saved.rename(bak)
    r = webapp.regen_audio([1], auto=False)
    assert not r.get("ok") and "script.txt" in (r.get("error") or ""), f"[5] 실패: {r}"
    bak.rename(saved)
    print("[5] ✅ script.txt 없음 → 안전한 에러 반환")

    print("\n🎉 /api/tts 음성 즉시 재생성 검증 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
