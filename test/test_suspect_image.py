# -*- coding: utf-8 -*-
"""생성 실패(단색) 이미지 검증 · base 승격 안전화 · 삽입 이미지 검증 테스트

배경 (2026-09-23 P0 사고):
  ① SD(fp16) 오버플로로 scene_01 이 '회색 단색'으로 성공 처리돼 저장 →
     base 원본까지 회색으로 오염 ("base 가 이상한 이미지로 덮였다")
  ② 삽입 이미지로 빈/단색 이미지가 들어가도 경고 없이 저장 → "삽입이 안 보임"
  ③ 어제 추가한 base 승격 로직이 위 ①의 회색 이미지를 원본으로 굳혀버림

이 테스트는 (a) 단색 검출, (b) 승격 금지, (c) 업로드 경고, (d) SD 재시도·보존을
실제 output 을 건드리지 않고(temp 격리) 검증한다.

사용: .\\venv\\Scripts\\python.exe -X utf8 test\\test_suspect_image.py
"""
import base64
import io
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

from PIL import Image  # noqa: E402
from modules import overlay, script_store, image_gen  # noqa: E402
import webapp  # noqa: E402

FAILED = []


def check(name: str, cond: bool, extra: str = ""):
    print(("[OK] " if cond else "[FAIL] ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILED.append(name)


def gray_image(size=(800, 600)):
    """생성 실패 재현용: 단색 회색"""
    return Image.new("RGB", size, (190, 190, 190))


def noisy_image(size=(800, 600)):
    """정상 이미지 재현용: 큰 색 블록(밝기 편차 큼) — 실제 웹툰 이미지와 유사"""
    from PIL import ImageDraw
    img = Image.new("RGB", size, (240, 240, 240))
    d = ImageDraw.Draw(img)
    w, h = size
    cols = [(30, 60, 200), (220, 40, 40), (40, 180, 80), (250, 200, 40)]
    for i, c in enumerate(cols):
        x0 = int(w * (i % 2) / 2)
        y0 = int(h * (i // 2) / 2)
        d.rectangle([x0, y0, x0 + w // 2, y0 + h // 2], fill=c)
    return img


def data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


class FakePipe:
    """SD 파이프 mock — 미리 정한 이미지를 순서대로 반환"""
    def __init__(self, images):
        self.images = images
        self.calls = 0

    def __call__(self, **kwargs):
        class R:
            pass
        r = R()
        r.images = [self.images[min(self.calls, len(self.images) - 1)]]
        self.calls += 1
        return r


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="saas_suspect_"))
    script_store.set_output_dir(tmp)
    overlay.OUTPUT_DIR = str(tmp)
    try:
        # ---------- [1] 단색 검출 ----------
        bad, why = overlay.is_suspect_pil_image(gray_image())
        check("[1-1] 단색 회색 → 의심 판정", bad, why)
        bad, why = overlay.is_suspect_pil_image(noisy_image())
        check("[1-2] 정상 패턴 → 정상 판정", not bad, why)

        gf = tmp / "images" / "gray.png"
        gf.parent.mkdir(parents=True, exist_ok=True)
        gray_image().save(gf)
        nf = tmp / "images" / "noisy.png"
        noisy_image().save(nf)
        check("[1-3] 파일 버전 - 단색", overlay.is_suspect_image(gf)[0])
        check("[1-4] 파일 버전 - 정상", not overlay.is_suspect_image(nf)[0])

        # ---------- [2] base 승격 안전화 ----------
        # 2-1) 단색 final + base 없음 → 승격 금지 (base 가 생기면 안 됨)
        overlay.final_path(1).parent.mkdir(parents=True, exist_ok=True)
        gray_image((1080, 1920)).save(overlay.final_path(1))
        res = overlay.apply_scene(1, text="테스트 대사")
        check("[2-1a] 합성 자체는 성공(기존 동작 유지)", res.get("ok"), str(res))
        check("[2-1b] 단색 final 은 base 로 승격되지 않음", not overlay.base_path(1).exists())

        # 2-2) 정상 final + base 없음 → 승격됨 (기존 기능 유지)
        noisy_image((1080, 1920)).save(overlay.final_path(2))
        res = overlay.apply_scene(2, text="테스트 대사")
        check("[2-2] 정상 final 은 base 로 승격", overlay.base_path(2).exists())

        # ---------- [3] sync_missing_bases 안전화 ----------
        gray_image((1080, 1920)).save(overlay.final_path(3))     # 단색, base 없음
        noisy_image((1080, 1920)).save(overlay.final_path(4))    # 정상, base 없음
        rep = overlay.sync_missing_bases(script=[{"scene": i} for i in range(1, 5)])
        check("[3-1] 단색(3번)은 보존 대상에서 제외", 3 in rep["missing"])
        check("[3-2] 정상(4번)은 원본으로 보존", 4 in rep["saved"])

        # ---------- [4] 삽입/원본 업로드 검증 ----------
        # 4-1) 단색 삽입 → warn 경고 + 저장 (장면 5: 정상 배경 준비)
        noisy_image((1080, 1920)).save(overlay.final_path(5))
        r = webapp.upload_insert_image(5, data_url(gray_image()))
        check("[4-1] 단색 삽입 → 경고 포함", r.get("ok") and bool(r.get("warn")), str(r))

        # 4-2) 정상 삽입 → 경고 없음
        old_final = overlay.final_path(6)
        noisy_image((1080, 1920)).save(old_final)
        r = webapp.upload_insert_image(6, data_url(noisy_image((300, 200))))
        check("[4-2] 정상 삽입 → 경고 없음", r.get("ok") and not r.get("warn"), str(r))

        # 4-3) 초소형 이미지 → 거부
        r = webapp.upload_insert_image(7, data_url(Image.new("RGB", (10, 10), (255, 0, 0))))
        check("[4-3] 초소형(10x10) 삽입 거부", not r.get("ok"), str(r))

        # 4-4) 단색 원본(base) 업로드 → 경고
        r = webapp.upload_base_image(8, data_url(gray_image((400, 700))))
        check("[4-4] 단색 원본 업로드 → 경고 포함", r.get("ok") and bool(r.get("warn")), str(r))

        # ---------- [5] SD 생성 검증 + 재시도 ----------
        ig = image_gen.ImageGenerator(mode="sd_local")
        ig.output_dir = tmp / "images"
        ig._build_sd_prompt = lambda p: "test prompt"

        # 5-1) 계속 단색 → 저장하지 않고 None (기존 이미지 보존)
        keep = tmp / "images" / "scene_09.png"
        noisy_image((1080, 1920)).save(keep)                  # 기존 정상 이미지
        before = keep.read_bytes()
        ig._load_sd_local = lambda: FakePipe([gray_image((576, 1024)), gray_image((576, 1024))])
        out = ig.generate_with_sd_local("테스트", 9)
        check("[5-1a] 2회 모두 단색 → None 반환", out is None, str(out))
        check("[5-1b] 기존 이미지 파일 보존됨", keep.read_bytes() == before)

        # 5-2) 첫 회 단색 → 재시도에서 정상 → 저장 성공
        ig._load_sd_local = lambda: FakePipe([gray_image((576, 1024)), noisy_image((576, 1024))])
        out = ig.generate_with_sd_local("테스트", 10)
        check("[5-2a] 재시도로 정상 생성 → 저장", bool(out) and Path(out).exists(), str(out))
        check("[5-2b] 저장된 이미지가 정상 판정", bool(out) and not overlay.is_suspect_image(out)[0])

        print()
        if FAILED:
            print(f"❌ 실패 {len(FAILED)}건: {FAILED}")
            return 1
        print("✅ 전체 통과 (12개 검사)")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

