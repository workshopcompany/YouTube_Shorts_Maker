# -*- coding: utf-8 -*-
"""이미지 삽입(박아 넣기) 기능 검증 — PIL만 사용 (API·SD 호출 없음)

사용: .\\venv\\Scripts\\python.exe -X utf8 test\\test_insert.py
"""
import io
import sys
import base64
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from PIL import Image                                     # noqa: E402
from modules import overlay as ov                         # noqa: E402
from modules import script_store                          # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="saas_ins_"))
script_store.set_output_dir(str(TMP))
ov.OUTPUT_DIR = str(TMP)        # overlay 는 config.OUTPUT_DIR 를 모듈 전역으로 사용
                                # → 패치 없으면 실제 output 을 덮어쓴다 (2026-09-24 사고)

BASE_W, BASE_H = 1080, 1920


def make_base(path: Path):
    """삽입 영역과 구별되는 패턴 배경 (밝은 회색)"""
    img = Image.new("RGB", (BASE_W, BASE_H), (200, 200, 200))
    for y in range(0, BASE_H, 40):
        for x in range(0, BASE_W, 40):
            if (x // 40 + y // 40) % 2 == 0:
                img.paste((180, 180, 180), (x, y, min(x + 40, BASE_W), min(y + 40, BASE_H)))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return img


def make_insert():
    """선명한 빨간 삽입 이미지 (800x600 → 가로세로 비율 4:3)"""
    return Image.new("RGB", (800, 600), (220, 30, 30))


def center_pixels(img, cx_ratio, cy_ratio, span=0.02):
    """비율 좌표 주변 픽셀 색 목록"""
    W, H = img.size
    cx, cy = int(W * cx_ratio), int(H * cy_ratio)
    half = int(W * span)
    px = img.convert("RGB")
    return [px.getpixel((max(0, min(W - 1, cx + dx)), max(0, min(H - 1, cy + dy))))
            for dx in range(-half, half + 1, max(half, 1))
            for dy in range(-half, half + 1, max(half, 1))]


def is_reddish(px) -> bool:
    r, g, b = px
    return r > 150 and g < 110 and b < 110


def cfg(**kw):
    c = ov.load_config()
    c.update({"enabled": True, "frame": "rect", "x": 0.5, "y": 0.5,
              "w": 0.4, "h": 0.3, "border_width": 8, "shadow": False})
    c.update(kw)
    return c


def main() -> int:
    base_p = ov.base_path(1)
    make_base(base_p)
    ins = make_insert()

    # [1] rect 프레임: 중앙 삽입 → 중심은 빨강, 코너는 배경 유지
    out = ov.draw_insert(make_base(base_p), ins, cfg())
    assert out.size == (BASE_W, BASE_H), f"[1] 크기 변경: {out.size}"
    assert all(is_reddish(p) for p in center_pixels(out, 0.5, 0.5)), "[1] 중심이 삽입 이미지 아님"
    assert not any(is_reddish(p) for p in center_pixels(out, 0.05, 0.05)), "[1] 코너까지 침범"
    print("[1] ✅ rect 프레임: 중앙 삽입 + 주변 배경 유지")

    # [2] 프레임 4종 모두 결과가 서로 다르고 삽입은 정상 위치에
    outs = {}
    for style in ("rect", "rounded", "tv", "frame"):
        o = ov.draw_insert(make_base(base_p), ins, cfg(frame=style, border_width=12))
        outs[style] = o
        assert all(is_reddish(p) for p in center_pixels(o, 0.5, 0.5)), f"[2] {style} 중심 누락"
    assert len({o.tobytes() for o in outs.values()}) == 4, "[2] 스타일 간 결과 동일"
    print("[2] ✅ 프레임 4종(rect/rounded/tv/frame) 상이 + 삽입 위치 정상")

    # [3] 위치 이동: 좌상단 vs 우하단
    tl = ov.draw_insert(make_base(base_p), ins, cfg(x=0.15, y=0.15))
    br = ov.draw_insert(make_base(base_p), ins, cfg(x=0.85, y=0.85))
    assert all(is_reddish(p) for p in center_pixels(tl, 0.15, 0.15)), "[3] 좌상단 배치 실패"
    assert all(is_reddish(p) for p in center_pixels(br, 0.85, 0.85)), "[3] 우하단 배치 실패"
    assert not any(is_reddish(p) for p in center_pixels(tl, 0.85, 0.85)), "[3] 좌상단이 우하단 침범"
    print("[3] ✅ 위치 조절 (좌상단/우하단)")

    # [4] 크기 조절: 폭 20% vs 70%
    small = ov.draw_insert(make_base(base_p), ins, cfg(w=0.2))
    large = ov.draw_insert(make_base(base_p), ins, cfg(w=0.7))
    small_cnt = sum(1 for x in range(0, BASE_W, 10) for y in range(0, BASE_H, 10)
                    if is_reddish(small.convert("RGB").getpixel((x, y))))
    large_cnt = sum(1 for x in range(0, BASE_W, 10) for y in range(0, BASE_H, 10)
                    if is_reddish(large.convert("RGB").getpixel((x, y))))
    assert large_cnt > small_cnt * 3, f"[4] 크기 조절 실패: {small_cnt} vs {large_cnt}"
    print(f"[4] ✅ 크기 조절 (빨강 픽셀 {small_cnt} → {large_cnt})")

    # [5] 비율 유지: 4:3 삽입 → 삽입 영역도 4:3 근접
    o = ov.draw_insert(make_base(base_p), ins, cfg(w=0.5, h=0.9, keep_ratio=True))
    rgb = o.convert("RGB")
    xs = [x for x in range(0, BASE_W, 2) if is_reddish(rgb.getpixel((x, BASE_H // 2)))]
    ys = [y for y in range(0, BASE_H, 2) if is_reddish(rgb.getpixel((BASE_W // 2, y)))]
    ratio = (max(xs) - min(xs)) / max(max(ys) - min(ys), 1)
    assert 1.15 < ratio < 1.65, f"[5] 비율 유지 실패: {ratio:.2f} (기대 1.33 근처)"
    print(f"[5] ✅ 비율 유지 (4:3=1.33 기대 → 실측 {ratio:.2f})")

    # [6] enabled=False 여도 draw_insert 는 그린다 (합성 게이트는 '삽입 파일 존재' 기준)
    same = ov.draw_insert(make_base(base_p), ins, cfg(enabled=False))
    assert any(is_reddish(p) for p in center_pixels(same, 0.5, 0.5)), \
        "[6] enabled=False 에서 삽입 누락 — 부분 저장 리셋 버그 재발"
    print("[6] ✅ enabled=False 여도 삽입 유지 (파일 존재 = 사용 의사)")

    # [7] apply_scene 통합: base + 삽입 이미지 저장 → 최종 이미지에 반영
    #     (설정 파일 enabled=False 여도 파일이 있으면 합성 — 부분 저장 리셋 버그 회귀 방지)
    ins_p = ov.insert_path(1)
    ins.save(ins_p)
    ov.save_config(cfg(enabled=False))
    res = ov.apply_scene(1)
    assert res.get("ok"), f"[7] apply 실패: {res}"
    final = Image.open(ov.final_path(1)).convert("RGB")
    assert all(is_reddish(p) for p in center_pixels(final, 0.5, 0.5)), "[7] 최종 이미지에 삽입 누락"
    kept = Image.open(ov.base_path(1)).convert("RGB")
    assert not any(is_reddish(p) for p in center_pixels(kept, 0.5, 0.5)), "[7] base 오염"
    print("[7] ✅ apply_scene 통합 (최종 반영 + base 원본 보존)")

    # [8] render_preview: 축소 미리보기에도 삽입 반영
    p = ov.render_preview(1, cfg=cfg(enabled=False))
    assert p and Path(p).exists(), "[8] 미리보기 실패"
    pv = Image.open(p).convert("RGB")
    W, H = pv.size
    assert is_reddish(pv.getpixel((W // 2, H // 2))), "[8] 미리보기에 삽입 누락"
    print(f"[8] ✅ 미리보기 삽입 반영 ({W}x{H})")

    # [9] insert_key: 설정 변경 시 해시 변화
    k1 = ov.insert_key(1, cfg())
    k2 = ov.insert_key(1, cfg(w=0.6))
    assert k1 != k2, "[9] 설정 변경이 해시에 반영 안 됨"
    print("[9] ✅ insert_key 설정 반영")

    # [10] 웹 서버 함수: data URL 업로드 → insert 저장
    import webapp
    buf = io.BytesIO()
    ins.save(buf, format="PNG")
    data_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    webapp.upload_insert_image(2, data_url)
    assert ov.insert_path(2).exists(), "[10] insert 저장 실패"
    print("[10] ✅ 웹 업로드 API (data URL → insert 저장)")

    # [11] 부분 저장: 텍스트 설정만 보내도 삽입 설정이 초기화되지 않는다
    #      (기존 버그: saveCfg → readCfg()만 전송 → enabled=False 로 리셋 → 삽입 사라짐)
    ov.save_config(cfg(enabled=True, w=0.5, x=0.3))
    ov.save_config({"style": "caption", "font_size": 60})     # 텍스트 키만 전송
    after = ov.load_config()
    assert after.get("enabled") is True, "[11] 텍스트만 저장 시 enabled 리셋됨 (버그 재발)"
    assert abs(float(after.get("w")) - 0.5) < 1e-9, "[11] 텍스트만 저장 시 삽입 크기 리셋됨"
    assert abs(float(after.get("x")) - 0.3) < 1e-9, "[11] 텍스트만 저장 시 삽입 위치 리셋됨"
    assert after.get("style") == "caption", "[11] 텍스트 설정 반영 안 됨"
    assert int(after.get("font_size")) == 60, "[11] 글자 크기 반영 안 됨"
    print("[11] ✅ 부분 저장 시 삽입 설정 유지 (enabled/위치/크기 보존)")

    # [12] 삽입 설정(위치·크기) 변경이 '다시 그리기 대상'으로 감지되어야 한다
    #      (수정 전: overlay_sig 가 텍스트만 봐서 미리보기와 영상이 달라지는 원인)
    script_store.save_script_file([{"content": "첫 장면", "visual": "v1"},
                                   {"content": "둘째 장면", "visual": "v2"}])
    ins2 = make_insert()
    ins2.save(ov.insert_path(1))
    ov.save_config(cfg(enabled=True, x=0.3, y=0.3, w=0.4, h=0.3))
    res = ov.apply_scene(1)                              # mark=True → 현재 해시 기록
    assert res.get("ok"), f"[12] apply 실패: {res}"
    st_now = script_store.load_state()
    rows = script_store.scene_status(state=st_now, overlay_key=ov.current_key)
    row1 = next(r for r in rows if r["scene"] == 1)
    assert not row1["overlay_changed"], f"[12] 방금 그린 장면이 '변경됨'으로 잡힘: {row1}"
    ov.save_config(cfg(enabled=True, x=0.3, y=0.7, w=0.4, h=0.3))   # 위치만 변경
    rows2 = script_store.scene_status(state=script_store.load_state(), overlay_key=ov.current_key)
    row1b = next(r for r in rows2 if r["scene"] == 1)
    assert row1b["overlay_changed"], "[12] 삽입 위치 변경이 감지 안 됨 (영상 미갱신 버그 재발)"
    # 삽입 제거도 감지되어야 한다 (원본+텍스트로 되돌리기)
    ov.insert_path(1).unlink()
    rows3 = script_store.scene_status(state=script_store.load_state(), overlay_key=ov.current_key)
    row1c = next(r for r in rows3 if r["scene"] == 1)
    assert row1c["overlay_changed"], "[12] 삽입 제거가 감지 안 됨"
    print("[12] ✅ 삽입 위치 변경·삽입 제거가 '다시 그리기' 대상으로 감지됨")

    print("\n🎉 이미지 삽입(박아 넣기) 검증 통과")


if __name__ == "__main__":
    sys.exit(main())
