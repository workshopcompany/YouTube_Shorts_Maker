# -*- coding: utf-8 -*-
"""이미지 텍스트 합성(대사 붙여넣기) 검증 — API/SD 호출 없이 PIL만 사용

사용: .\\venv\\Scripts\\python.exe -X utf8 scripts\\test_overlay.py
"""
import hashlib
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

from PIL import Image, ImageDraw  # noqa: E402
from modules import overlay, script_store  # noqa: E402

BG = (200, 210, 230)


def whiteness(img: Image.Image, y0: float, y1: float) -> float:
    """지정 세로 구간에서 흰색(박스) 픽셀 비율"""
    W, H = img.size
    crop = img.convert("RGB").crop((0, int(H * y0), W, int(H * y1)))
    data = list(crop.getdata())
    white = sum(1 for r, g, b in data if r > 240 and g > 240 and b > 240)
    return white / max(1, len(data))


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="saas_overlay_"))
    script_store.set_output_dir(tmp)
    overlay.OUTPUT_DIR = str(tmp)          # overlay 는 config.OUTPUT_DIR 를 모듈 전역으로 사용
    try:
        scenes = [
            {"scene": 1, "time": "0~5초", "content": "대사 텍스트를 이미지에 붙여넣는 테스트입니다",
             "visual": "테스트 배경"},
            {"scene": 2, "time": "5~10초", "content": "두 번째 장면의 아주 긴 대사입니다. 박스 안에서 자동으로 줄바꿈이 되어야 하며 너무 길면 글자가 작아집니다.",
             "visual": "테스트 배경"},
        ]
        script_store.save_script_file(scenes)

        # [1] 생성 직후 이미지(base) 보관 → 두 파일이 동일해야 함
        for i in (1, 2, 3):
            f = overlay.final_path(i)
            f.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (1080, 1920), BG).save(f)
            overlay.save_base_from(f, i)
        final1 = overlay.final_path(1)
        base1 = overlay.base_path(1)
        assert base1.exists() and md5(base1) == md5(final1), "base 보관 실패"
        print("[1] ✅ 원본(base) 이미지 보관 확인")

        # [2] 말풍선(상단) — 위쪽에 흰 박스가 생기고 아래쪽은 그대로
        cfg = overlay.save_config({"style": "bubble", "position": "top", "font_size": 52,
                                   "box_alpha": 255, "max_lines": 5})
        res = overlay.apply_scene(1, cfg=cfg, mark=False)
        assert res["ok"] and res["used_base"], res
        img_top = Image.open(final1)
        top_white = whiteness(img_top, 0.05, 0.25)
        bottom_white = whiteness(img_top, 0.70, 0.95)
        assert top_white > 0.20, f"상단 말풍선이 안 보임 (white={top_white:.3f})"
        assert bottom_white < 0.02, f"하단에 불필요한 박스 (white={bottom_white:.3f})"
        assert md5(base1) != md5(final1), "합성 결과가 원본과 동일(그려지지 않음)"
        print(f"[2] ✅ 말풍선 상단 배치 (상단 흰비율 {top_white:.2f} / 하단 {bottom_white:.3f})")

        # [3] 위치 'bottom' → 아래쪽에 박스
        cfg = overlay.save_config({"style": "bubble", "position": "bottom", "font_size": 52,
                                   "box_alpha": 255})
        overlay.apply_scene(1, cfg=cfg, mark=False)
        img_bottom = Image.open(final1)
        assert whiteness(img_bottom, 0.70, 0.95) > 0.20, "하단 말풍선이 안 보임"
        assert whiteness(img_bottom, 0.05, 0.25) < 0.02, "상단에 박스가 남음"
        print("[3] ✅ 말풍선 하단 배치 확인")

        # [4] 스타일 3종 + none 비교
        hashes = {}
        for style in ("bubble", "caption", "outline"):
            overlay.save_config({"style": style, "position": "top"})
            overlay.apply_scene(2, cfg=overlay.load_config(), mark=False)
            hashes[style] = md5(overlay.final_path(2))
            print(f"    - {style}: 흰비율 {whiteness(Image.open(overlay.final_path(2)), 0.05, 0.30):.3f}")
        assert len(set(hashes.values())) == 3, "스타일별 결과가 동일함"

        overlay.save_config({"style": "none"})
        overlay.apply_scene(2, cfg=overlay.load_config(), mark=False)
        assert md5(overlay.base_path(2)) == md5(overlay.final_path(2)), "style=none 인데 텍스트가 그려짐"
        print("[4] ✅ 스타일 3종 결과 상이 + style=none 은 원본 유지")

        # [5] 미리보기(축소) 렌더링
        overlay.save_config({"style": "bubble", "position": "top"})
        pv = overlay.render_preview(1, cfg=overlay.load_config(), max_w=540)
        assert pv and Path(pv).exists(), "미리보기 생성 실패"
        assert Image.open(pv).size[0] == 540, Image.open(pv).size
        print(f"[5] ✅ 미리보기 생성: {Path(pv).name} {Image.open(pv).size}")

        # [6] base 가 없는(예전 방식) 이미지에도 합성 가능해야 함
        #     — 최신 동작: 합성 전에 현재 이미지를 base로 승격해 원본을 보존한 뒤 합성
        #     (단색/저분산 '생성실패 의심' 이미지는 승격 금지 → test_suspect_image.py 에서 검증)
        orphan = overlay.final_path(4)
        orphan_img = Image.new("RGB", (1080, 1920), BG)
        ImageDraw.Draw(orphan_img).rectangle([0, 1300, 1080, 1920], fill=(60, 90, 160))
        orphan_img.save(orphan)
        assert not overlay.base_path(4).exists(), "준비 조건: base가 없어야 함"
        res3 = overlay.apply_scene(4, text="예전 이미지 위에 다시 그리기", cfg=overlay.load_config(), mark=False)
        assert res3["ok"], res3
        assert res3["legacy"] is False and res3["used_base"] is True, res3
        assert overlay.base_path(4).exists(), "base 승격(원본 보존)이 되지 않음"
        assert whiteness(Image.open(orphan), 0.05, 0.25) > 0.20, "이미지에 박스가 안 그려짐"
        print("[6] ✅ base 없는 기존 이미지 → base 승격 후 텍스트 합성")

        # [7] 긴 대사 자동 줄바꿈/축소 (최대 줄 수 이내)
        long_text = "아주 긴 대사 " * 40
        img = overlay.draw_text(Image.new("RGB", (1080, 1920), BG), long_text,
                                {"style": "bubble", "position": "top", "font_size": 52, "max_lines": 5})
        assert whiteness(img, 0.03, 0.55) > 0.05, "긴 대사 박스가 그려지지 않음"
        print("[7] ✅ 긴 대사 자동 줄바꿈/축소 동작")
    finally:
        overlay.OUTPUT_DIR = str(Path(ROOT) / "output")
        script_store.set_output_dir(Path(ROOT) / "output")
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    main()
    print("\n🎉 이미지 텍스트 합성 검증 통과")
