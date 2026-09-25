"""직접 수정(옵션 7) + 한자 감지 기능 검증 — API 호출 없이 stdin 시뮬레이션
사용: .venv\\Scripts\\python.exe -X utf8 scripts\\test_direct_edit.py"""
import io
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
import main


def feed(inputs):
    sys.stdin = io.StringIO("\n".join(inputs) + "\n")


script = [
    {"scene": 1, "time": "0~5초", "content": "안녕하세요! 오늘은 쇼츠 만드는 법을 알려드릴게요.", "visual": "밝은 방에서 너구리가 인사하는 장면"},
    {"scene": 2, "time": "5~10초", "content": "퇴근前要 이렇게 한자가 섞여 나오는 경우가 있어요.", "visual": "화면에 한자가 표시된 장면"},
    {"scene": 3, "time": "10~15초", "content": "프롬프트 하나로 대본과 이미지가 자동으로 만들어집니다.", "visual": "자동화 흐름을 보여주는 장면"},
]

# 1) 한자 감지
assert main.has_hanja("퇴근前要") is True
assert main.has_hanja("안녕하세요 반갑습니다") is False
print("[1] ✅ has_hanja: 한자 감지 정상")

# 2) 직접 수정 — 장면 2 내용만 교체, 시각은 엔터(유지), 이후 엔터(종료)
feed(["2", "퇴근길이 얼마나 기다려지는지 요즘 정말 많이 느껴져요", "", ""])
out = main.edit_scene_direct(script)
assert out[1]["content"] == "퇴근길이 얼마나 기다려지는지 요즘 정말 많이 느껴져요", out[1]
assert out[1]["visual"] == "화면에 한자가 표시된 장면"
assert main.has_hanja(out[1]["content"]) is False
print("[2] ✅ 직접 수정: 장면 2 내용 교체 + 시각 유지(엔터) + 한자 제거 확인")

# 3) 잘못된 입력 — 범위 초과/문자 → 경고 후 계속, 장면 3은 엔터(유지), 마지막 엔터로 종료
feed(["99", "abc", "3", "", "", ""])
out2 = main.edit_scene_direct(script)
assert out2[2]["content"] == script[2]["content"]
assert out2[0]["content"] == script[0]["content"]
print("[3] ✅ 잘못된 입력 처리: 범위초과/문자 경고 후 정상 계속, 대본 훼손 없음")

# 4) 원본 불변 (deepcopy 확인)
assert script[1]["content"] != out[1]["content"]
print("[4] ✅ deepcopy: 원본 대본 보존 확인")

print("\n🎉 전체 검증 통과")
