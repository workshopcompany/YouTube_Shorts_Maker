# -*- coding: utf-8 -*-
"""이미지 텍스트 합성(붙여넣기) 모듈

생성된 장면 이미지에 '장면 대사(내용)'를 자동으로 그려 넣는다.
    - 스타일: 말풍선(bubble) / 자막 박스(caption) / 외곽선 글씨(outline) / 사용 안 함(none)
    - 위치: 상단(top) / 중앙(middle) / 하단(bottom)
    - 글자 크기·색·박스 투명도까지 조절 가능

핵심: 이미지를 새로 만들 때 **원본(텍스트 없는) 이미지를 output/images/base/ 에 보관**한다.
      → 대사만 고쳤을 때는 API/SD를 다시 부르지 않고, 원본 위에 텍스트만 다시 그리면 끝.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from config import OUTPUT_DIR, SPEECH_BUBBLE, BUBBLE_FONT_SIZE
from modules import script_store

STYLES = ("bubble", "caption", "outline", "none")
STYLES = ("bubble", "caption", "outline", "none")
POSITIONS = ("top", "middle", "bottom")

# 이미지 삽입(박아 넣기) 프레임 스타일
INSERT_FRAMES = ("rect", "rounded", "tv", "frame")

DEFAULT_INSERT = {
    "enabled": False,        # 삽입 기능 사용 여부
    "frame": "rect",         # rect | rounded | tv | frame
    "x": 0.5,                # 중심 X (0~1, 이미지 폭 비율)
    "y": 0.5,                # 중심 Y (0~1, 이미지 높이 비율)
    "w": 0.4,                # 폭 (0~1, 이미지 폭 비율)
    "h": 0.3,                # 높이 (0~1, 이미지 높이 비율)
    "border_width": 8,       # 프레임 테두리 두께
    "border_color": "#222222",
    "frame_color": "#8B5A2B",  # 액자 프레임 색
    "tv_color": "#111111",     # TV 베젤 색
    "shadow": True,          # 그림자 효과
    "keep_ratio": True,      # 가로세로 비율 유지 (비율 유지 시 h는 최대치로 사용)
}
POSITIONS = ("top", "middle", "bottom")

DEFAULT_CONFIG = {
    "style": "bubble",        # bubble | caption | outline | none
    "position": "top",        # top | middle | bottom
    "font_size": int(BUBBLE_FONT_SIZE or 52),
    "text_color": "#111111",
    "box_color": "#FFFFFF",
    "box_alpha": 235,         # 0=완전 투명, 255=불투명
    "outline_color": "#FFFFFF",
    "outline_width": 6,
    "border_color": "#111111",
    "border_width": 6,
    "max_lines": 5,
    "min_font_size": 26,
    "margin_x": 0.07,         # 좌우 여백 (이미지 폭 대비)
    "margin_y": 0.055,        # 상/하 여백 (top/bottom 배치 기준)
    "letter": "malgunbd",     # 폰트 힌트 (Windows 맑은고딕)
}

CONFIG_NAME = "overlay_config.json"


# ---------- 경로 ----------
def _out() -> Path:
    p = Path(OUTPUT_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_path() -> Path:
    return _out() / CONFIG_NAME


def base_dir() -> Path:
    d = _out() / "images" / "base"
    d.mkdir(parents=True, exist_ok=True)
    return d


def insert_dir() -> Path:
    """장면에 삽입할 사용자 이미지 보관 폴더"""
    d = _out() / "images" / "inserts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def insert_path(idx) -> Path:
    """장면별 삽입 이미지 저장 경로 (장면당 1개, 교체 시 덮어씀)"""
    p = insert_dir() / f"scene_{int(idx):02d}"
    # 원본 확장자 보존 (png/jpg/webp 등)
    if p.with_suffix(".png").exists():
        return p.with_suffix(".png")
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"):
        c = insert_dir() / f"scene_{int(idx):02d}{ext}"
        if c.exists():
            return c
    return p.with_suffix(".png")


def preview_dir() -> Path:
    d = _out() / "previews"
    d.mkdir(parents=True, exist_ok=True)
    return d


def base_path(idx) -> Path:
    return base_dir() / f"scene_{int(idx):02d}.png"


def final_path(idx) -> Path:
    return _out() / "images" / f"scene_{int(idx):02d}.png"


def preview_path(idx) -> Path:
    return preview_dir() / f"scene_{int(idx):02d}.png"


# ---------- 설정 ----------
def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(DEFAULT_INSERT)          # 삽입 기능 기본값 포함
    p = config_path()
    if p.exists():
        try:
            loaded = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cfg.update({k: v for k, v in loaded.items() if k in cfg})
        except Exception as e:
            print(f"⚠️ overlay_config.json 읽기 실패 (기본값 사용): {e}")
    else:
        # 최초 실행: 기존 config.py 의 SPEECH_BUBBLE 설정을 이어받는다
        cfg["style"] = "bubble" if SPEECH_BUBBLE else "none"
    return cfg


def save_config(cfg: dict) -> dict:
    """부분 저장 지원: 넘어오지 않은 키는 '기존 파일 값'을 그대로 유지한다.

    (기존 구현은 매번 기본값 위에 덮어써서, 텍스트 설정만 저장하면
     삽입 설정 enabled 등이 기본값 False 로 리셋되는 버그가 있었다.)
    """
    merged = load_config()              # 기본값 + 기존 파일 값
    merged.update({k: v for k, v in (cfg or {}).items() if k in merged})
    config_path().write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def current_key(scene: dict, cfg: dict = None, idx: int = None) -> str:
    """장면 대사 + 설정 → 합성 해시 (설정을 바꾸면 '다시 그리기 대상'으로 잡히게 함)

    idx 를 주면 그 장면의 '삽입 이미지 + 삽입 설정' 해시까지 섞는다.
      → 삽입 위치·크기·프레임을 바꾸거나 삽입 이미지를 교체해도 재합성 대상으로
        잡히고(영상도 다시 생성됨), 미리보기와 영상이 달라지는 일이 없다.
      → 삽입 이미지가 없는 장면은 기존 해시 그대로 유지(불필요한 재작업 없음)
    """
    cfg = cfg if cfg is not None else load_config()
    raw = json.dumps({k: cfg.get(k) for k in sorted(DEFAULT_CONFIG)}, ensure_ascii=False, sort_keys=True)
    parts = [raw, scene.get("content", "")]
    if idx is not None:
        try:
            if insert_path(idx).exists():
                parts.append(insert_key(idx, cfg))
        except Exception:
            pass
    return script_store.content_hash("|".join(parts))


def insert_key(idx, cfg: dict = None) -> str:
    """삽입 이미지 + 설정 → 삽입 합성 해시 (장면별 overlay_sig에 기록)"""
    cfg = cfg if cfg is not None else load_config()
    parts = [f"{k}={cfg.get(k)}" for k in sorted(DEFAULT_INSERT)]
    ip = insert_path(idx)
    if ip.exists():
        try:
            parts.append(f"file={ip.stat().st_size}_{int(ip.stat().st_mtime)}")
        except Exception:
            pass
    else:
        parts.append("file=none")
    return script_store.content_hash("|".join(parts))


# ---------- 폰트 ----------
def font_path(cfg: dict = None) -> str:
    hint = (cfg or {}).get("letter") or "malgunbd"
    candidates = [
        rf"C:\Windows\Fonts\{hint}.ttf",
        r"C:\Windows\Fonts\malgunbd.ttf",
        r"C:\Windows\Fonts\malgun.ttf",
        r"C:\Windows\Fonts\gulim.ttc",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return ""


def _hex(color, default=(17, 17, 17)) -> tuple:
    try:
        c = str(color).lstrip("#")
        if len(c) == 3:
            c = "".join(ch * 2 for ch in c)
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return default


def _wrap(draw, text: str, font, max_w: int) -> list:
    """공백 우선 줄바꿈, 긴 단어는 글자 단위 분할"""
    lines, cur = [], ""
    for word in str(text).split(" "):
        cand = (cur + " " + word).strip()
        if draw.textlength(cand, font=font) <= max_w:
            cur = cand
            continue
        if cur:
            lines.append(cur)
        while draw.textlength(word, font=font) > max_w and len(word) > 1:
            cut = len(word)
            while cut > 1 and draw.textlength(word[:cut], font=font) > max_w:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        cur = word
    if cur:
        lines.append(cur)
    return lines or [str(text)]


# ---------- 그리기: 이미지 삽입 (박아 넣기) ----------
def draw_insert(img: Image.Image, insert_img: Image.Image, cfg: dict = None,
                scale: float = 1.0) -> Image.Image:
    """기존 이미지 위에 사용자 이미지를 프레임 스타일로 삽입해 반환 (원본은 수정하지 않음)

    frame: rect(일반 사각형) | rounded(둥근 사각형) | tv(TV 화면) | frame(액자)
    x/y: 중심 위치(0~1), w/h: 크기(0~1) — keep_ratio=True 면 w 기준으로 비율 유지
    """
    cfg = cfg or load_config()
    if insert_img is None:
        return img

    # scale 은 미리보기 축소 배율 → 테두리 두께 등 픽셀 단위 값 배율에만 사용
    # (이미지 자체는 호출자가 미리 리사이즈해서 전달)
    W, H = img.size
    base = img.convert("RGBA")

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dl = ImageDraw.Draw(layer)

    def _f(key, default):
        try:
            return float(cfg.get(key, default))
        except (TypeError, ValueError):
            return float(default)

    def _i(key, default):
        try:
            return int(float(cfg.get(key, default)))
        except (TypeError, ValueError):
            return int(default)

    cx_ratio = min(max(_f("x", 0.5), 0.0), 1.0)
    cy_ratio = min(max(_f("y", 0.5), 0.0), 1.0)
    w_ratio = min(max(_f("w", 0.4), 0.02), 1.0)
    h_ratio = min(max(_f("h", 0.3), 0.02), 1.0)
    border_w = max(int(round(_i("border_width", 8) * (scale if scale else 1.0))), 0)
    frame_style = (cfg.get("frame") or "rect").lower()

    # 삽입 크기 계산
    iw = max(int(W * w_ratio), 20)
    if cfg.get("keep_ratio", True):
        # 가로세로 비율 유지 (h는 최대 높이 제한으로 사용)
        sw, sh = insert_img.size
        ih = max(int(iw * sh / max(sw, 1)), 20)
        ih = min(ih, max(int(H * h_ratio), 20))
        iw = max(int(iw * ih / max(ih, 1)), 20) if sh else iw
    else:
        ih = max(int(H * h_ratio), 20)

    # 프레임 두께만큼 내부 공간 확보
    bezel = border_w if frame_style in ("rect", "rounded") else border_w * 2
    inner_w = max(iw - bezel * 2, 20)
    inner_h = max(ih - bezel * 2, 20)

    # 삽입 이미지 준비 (내부 크기에 맞게 cover 크롭)
    ins = insert_img.convert("RGBA")
    sw, sh = ins.size
    cover_scale = max(inner_w / max(sw, 1), inner_h / max(sh, 1))
    ins = ins.resize((max(1, int(sw * cover_scale)), max(1, int(sh * cover_scale))), Image.LANCZOS)
    sw, sh = ins.size
    left = max(0, (sw - inner_w) // 2)
    top = max(0, (sh - inner_h) // 2)
    ins = ins.crop((left, top, left + inner_w, top + inner_h))

    # 중심 좌표로 변환
    bx = max(0, int(cx_ratio * W - iw / 2))
    by = max(0, int(cy_ratio * H - ih / 2))

    # 그림자
    if cfg.get("shadow", True):
        sh_pad = max(border_w * 2, 12)
        sh_layer = Image.new("RGBA", (W + sh_pad * 2, H + sh_pad * 2), (0, 0, 0, 0))
        ImageDraw.Draw(sh_layer).rectangle(
            [sh_pad + bx + 4, sh_pad + by + 6, sh_pad + bx + iw + 4, sh_pad + by + ih + 6],
            fill=(0, 0, 0, 90))
        sh_layer = sh_layer.filter(ImageFilter.GaussianBlur(radius=max(border_w, 6)))
        layer = Image.alpha_composite(layer, sh_layer.crop((sh_pad, sh_pad, sh_pad + W, sh_pad + H)))
        dl = ImageDraw.Draw(layer)

    # 프레임 본체
    if frame_style == "tv":
        # TV 베젤 (어두운 외곽 → 화면은 바로 붙임)
        tv_rgb = _hex(cfg.get("tv_color"), (17, 17, 17))
        dl.rounded_rectangle([bx, by, bx + iw, by + ih], radius=int(iw * 0.07),
                             fill=(*tv_rgb, 255))
        # 하단 스탠드 바
        dl.rounded_rectangle([bx + iw * 0.38, by + ih, bx + iw * 0.62, by + ih + border_w],
                             radius=max(border_w // 2, 1), fill=(*tv_rgb, 255))
    elif frame_style == "frame":
        # 액자: 외곽 프레임 + 흰색 매트(여백) + 사진
        fr_rgb = _hex(cfg.get("frame_color"), (139, 90, 43))
        dl.rounded_rectangle([bx, by, bx + iw, by + ih], radius=int(iw * 0.04),
                             fill=(*fr_rgb, 255))
        dl.rounded_rectangle([bx + border_w, by + border_w,
                              bx + iw - border_w, by + ih - border_w],
                             radius=int(iw * 0.025), fill=(255, 255, 255, 255))
    else:
        # rect / rounded: 테두리만
        border_rgb = _hex(cfg.get("border_color"), (34, 34, 34))
        radius = 0 if frame_style == "rect" else int(iw * 0.06)
        dl.rounded_rectangle([bx, by, bx + iw, by + ih], radius=radius,
                             fill=(255, 255, 255, 255) if border_w else (0, 0, 0, 0),
                             outline=(*border_rgb, 255) if border_w else None,
                             width=border_w if border_w else 0)

    # 삽입 이미지 붙이기 (모서리 마스크)
    if frame_style in ("rounded", "tv", "frame"):
        r = int(inner_w * 0.05)
        r = max(r, 5)
        mask = Image.new("L", (inner_w, inner_h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, inner_w - 1, inner_h - 1], radius=r, fill=255)
        layer.paste(ins, (bx + bezel, by + bezel), mask)
    else:
        layer.paste(ins, (bx + bezel, by + bezel))

    result = Image.alpha_composite(base, layer)
    return result.convert(base.mode if base.mode in ("RGB", "RGBA") else "RGB")


# ---------- 그리기: 텍스트 ----------
def draw_text(img: Image.Image, text: str, cfg: dict = None, scale: float = 1.0,
              legacy: bool = False) -> Image.Image:
    """이미지 위에 대사를 그려서 반환 (원본은 수정하지 않음)

    legacy=True: base 원본이 없어 이미 텍스트가 그려진 이미지 위에 덧그리는 경우
                 → 예전 글씨가 비쳐 보이지 않도록 박스를 불투명하게 채움
    """
    cfg = cfg or load_config()
    style = cfg.get("style", "bubble")
    if style == "none":
        return img
    clean = " ".join(str(text or "").split())
    if not clean:
        return img
    fp = font_path(cfg)
    if not fp:
        print("   ⚠ 텍스트 폰트(맑은고딕)를 찾지 못해 합성 생략")
        return img

    W, H = img.size
    canvas = img.convert("RGBA")
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    dl = ImageDraw.Draw(layer)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))

    margin_x = float(cfg.get("margin_x", 0.07))
    margin_y = float(cfg.get("margin_y", 0.055))
    max_w = max(int(W * (1 - 2 * margin_x)), 40)
    min_size = max(int(round(float(cfg.get("min_font_size", 26)) * scale)), 10)
    size = max(int(round(float(cfg.get("font_size", 52)) * scale)), min_size)
    max_lines = max(int(cfg.get("max_lines", 5)), 1)

    while True:
        font = ImageFont.truetype(fp, size)
        lines = _wrap(probe, clean, font, max_w)
        if len(lines) <= max_lines or size <= min_size:
            break
        size -= max(2, int(size * 0.08))

    line_h = int(size * 1.5)
    pad_x, pad_y = int(size * 0.9), int(size * 0.7)
    text_w = max(int(probe.textlength(l, font=font)) for l in lines)
    bw = min(max_w, text_w) + pad_x * 2
    bh = len(lines) * line_h + pad_y * 2
    x0 = (W - bw) // 2
    pos = cfg.get("position", "top")
    my = int(H * margin_y)
    if pos == "middle":
        y0 = max(0, (H - bh) // 2)
    elif pos == "bottom":
        y0 = max(my, H - my - bh)
    else:  # top
        y0 = my
    y1 = y0 + bh

    text_color = _hex(cfg.get("text_color"), (17, 17, 17))
    box_rgb = _hex(cfg.get("box_color"), (255, 255, 255))
    border_rgb = _hex(cfg.get("border_color"), (20, 20, 20))
    border_w = max(int(round(float(cfg.get("border_width", 6)) * scale)), 0)
    alpha = int(cfg.get("box_alpha", 235))
    if legacy and style in ("bubble", "caption"):
        alpha = 255  # 예전에 그려진 글씨를 완전히 덮음

    if style in ("bubble", "caption") or (legacy and style == "outline"):
        radius = int(size * 0.8) if style == "bubble" else int(size * 0.4)
        dl.rounded_rectangle([x0, y0, x0 + bw, y1], radius=radius,
                             fill=(*box_rgb, alpha),
                             outline=(*border_rgb, 255) if border_w else None,
                             width=border_w if border_w else 0)
        if style == "bubble" and pos in ("top", "bottom"):
            tail_w = int(size * 1.3)
            tail_h = int(size * 1.6)
            cx = W // 2
            if pos == "top":      # 아래(캐릭터) 방향
                t_edge = y1 - border_w
                apex = (cx + tail_w // 3, y1 + tail_h)
                pts = [(cx - tail_w, t_edge), (cx + tail_w, t_edge), apex]
            else:                 # 위 방향
                t_edge = y0 + border_w
                apex = (cx - tail_w // 3, y0 - tail_h)
                pts = [(cx - tail_w, t_edge), (cx + tail_w, t_edge), apex]
            dl.polygon(pts, fill=(*box_rgb, alpha))
            if border_w:
                dl.line([pts[0], pts[2]], fill=(*border_rgb, 255), width=border_w)
                dl.line([pts[1], pts[2]], fill=(*border_rgb, 255), width=border_w)

    canvas = Image.alpha_composite(canvas, layer)
    draw = ImageDraw.Draw(canvas)
    ty = y0 + pad_y
    stroke_w = max(int(round(float(cfg.get("outline_width", 6)) * scale)), 0)
    for line in lines:
        lw = draw.textlength(line, font=font)
        x = (W - lw) / 2
        if style == "outline":
            draw.text((x, ty), line, font=font, fill=text_color,
                      stroke_width=stroke_w,
                      stroke_fill=_hex(cfg.get("outline_color"), (255, 255, 255)))
        else:
            draw.text((x, ty), line, font=font, fill=text_color)
        ty += line_h
    return canvas.convert("RGB")


# ---------- 생성 실패(단색) 이미지 검증 ----------
def is_suspect_pil_image(img: Image.Image, std_threshold: float = 10.0) -> tuple:
    """단색/저분산(생성 실패 의심) 이미지 검출 → (의심 여부, 이유)

    SD(fp16) 오버플로 등으로 **회색·단색 이미지가 '성공'으로 저장**되는 사고를
    걸러내기 위한 검증. 정상 웹툰 이미지의 밝기 표준편차는 30 이상,
    실패 이미지는 10 미만(거의 평평)이다. (2026-09-23 base 회색 오염 사례)
    """
    try:
        from PIL import ImageStat
        # 리사이즈 없이 원본 밝기 분포로 계산 — 축소하면 세밀한 패턴이
        # 평균화되어 정상 이미지를 '단색'으로 오탐할 수 있다.
        st = ImageStat.Stat(img.convert("L"))
        std = sum(st.stddev) / len(st.stddev)
        if std < std_threshold:
            return True, f"단색/저분산 이미지 (밝기편차 {std:.1f})"
    except Exception as e:
        return False, f"검사 불가: {e}"
    return False, ""


def is_suspect_image(path, std_threshold: float = 10.0) -> tuple:
    """파일 경로 버전 — 열 수 없으면 (False, 사유)"""
    try:
        with Image.open(path) as im:
            return is_suspect_pil_image(im, std_threshold)
    except Exception as e:
        return False, f"검사 불가: {e}"


# ---------- 원본(base) 보관 및 자동 빈 이미지 생성 ----------
def placeholder_flag_path(idx) -> Path:
    """'아직 실제 이미지가 없다'는 표식 파일 경로 (원본 폴더에 함께 보관)"""
    return base_dir() / f"scene_{int(idx):02d}.placeholder"


def is_placeholder(idx) -> bool:
    """이 장면 원본이 AI 생성물이 아니라 임시 플레이스홀더인지 여부"""
    try:
        return placeholder_flag_path(idx).exists()
    except Exception:
        return False


def clear_placeholder_flag(idx) -> None:
    """실제 이미지가 들어왔으므로 '임시' 표식 제거"""
    try:
        fp = placeholder_flag_path(idx)
        if fp.exists():
            fp.unlink()
    except Exception:
        pass


def create_placeholder_base(idx: int, scene: dict = None) -> Path:
    """새 장면에 이미지가 아직 없을 때 깨짐 방지용 기본 빈 이미지(1080x1920)를 생성."""
    idx = int(idx)
    base = base_path(idx)
    final = final_path(idx)
    base.parent.mkdir(parents=True, exist_ok=True)
    final.parent.mkdir(parents=True, exist_ok=True)

    from PIL import ImageDraw, ImageFont
    import textwrap

    img = Image.new("RGB", (1080, 1920), (28, 30, 44))
    draw = ImageDraw.Draw(img)

    font_large, font_small = None, None
    for font_p in (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\gulim.ttc"):
        if os.path.exists(font_p):
            try:
                font_large = ImageFont.truetype(font_p, 72)
                font_small = ImageFont.truetype(font_p, 42)
                break
            except Exception:
                pass
    if not font_large:
        font_large = ImageFont.load_default()
        font_small = font_large

    title_text = f"장면 {idx}"
    sub_text = "🎨 이미지를 생성하세요 (새 이미지 만들기)"
    
    # 텍스트 중앙 배치
    draw.text((540, 850), title_text, fill=(240, 240, 245), font=font_large, anchor="mm")
    draw.text((540, 960), sub_text, fill=(160, 165, 185), font=font_small, anchor="mm")

    img.save(base)
    img.save(final)
    # 이 원본은 '임시'임을 기록 — UI에서 '정상'으로 보이지 않게 (실제 생성/업로드 시 자동 제거)
    try:
        placeholder_flag_path(idx).write_text("placeholder", encoding="utf-8")
    except Exception:
        pass
    return base


def save_base_from(src, idx, overwrite: bool = True) -> str:
    """생성 직후의 (텍스트 없는) 이미지를 base 폴더에 보관"""
    src = Path(src)
    if not src.exists():
        return ""
    dst = base_path(idx)
    if dst.exists() and not overwrite:
        return str(dst)
    shutil.copyfile(src, dst)
    clear_placeholder_flag(idx)   # 실제 원본이 들어왔으므로 '임시' 표식 제거
    return str(dst)


def has_base(idx) -> bool:
    return base_path(idx).exists()


def _is_base(p) -> bool:
    try:
        return Path(p).parent.resolve() == base_dir().resolve()
    except Exception:
        return False


# ---------- 적용 ----------
def _scene_content(idx: int) -> str:
    """script.txt 에서 해당 장면의 대사(내용) 가져오기"""
    script = script_store.load_script_file()
    if 0 < int(idx) <= len(script):
        return script[int(idx) - 1].get("content", "") or ""
    return ""


def apply_scene(idx, text: str = None, cfg: dict = None, src=None, dst=None,
                mark: bool = True, log=print) -> dict:
    """장면 이미지에 대사 텍스트를 그려 넣는다 (API 호출 없음).

    src 를 주지 않으면 ① base 원본 → ② (base가 없으면) 완성 이미지 순으로 사용한다.
    반환: {"ok":bool, "path":str, "used_base":bool, "legacy":bool}
    """
    idx = int(idx)
    cfg = cfg or load_config()
    base, final = base_path(idx), final_path(idx)
    # base 원본이 아직 없으면 현재 완성 이미지를 원본으로 보존
    # (재시작/재합성 시 옛 상태로 되돌아가는 현상 방지)
    # 단, '생성 실패 의심(단색 등)' 이미지는 승격 금지 — 회색 이미지가
    # 원본으로 굳어버리는 사고 방지 (2026-09-23 base 오염 사례)
    if not base.exists() and final.exists():
        suspect, why = is_suspect_image(final)
        if suspect:
            log(f"   ⚠ 장면 {idx:02d} 원본 승격 건너뜀 — {why}")
        else:
            try:
                save_base_from(final, idx, overwrite=False)
                base = base_path(idx)
            except Exception:
                pass
    src = Path(src) if src else (base if base.exists() else final)
    dst = Path(dst) if dst else final
    if not src.exists():
        # 이미지가 없으면 빈 플레이스홀더를 자동 생성하여 합성을 중단 없이 진행
        src = create_placeholder_base(idx)
        base = src
        used_base = True
    else:
        used_base = _is_base(src)
    try:
        img = Image.open(src)
        out = draw_text(img, text, cfg, legacy=not used_base)
        # 이미지 삽입(박아 넣기): 삽입 이미지가 등록되어 있으면 항상 합성
        # (enabled 플래그는 레거시 — 파일 존재 자체가 '사용 의사', 제거는 🗑 버튼으로)
        ip = insert_path(idx)
        if ip.exists():
            try:
                ins_img = Image.open(ip)
            except Exception:
                ins_img = None
            out = draw_insert(out, ins_img, cfg)
        dst.parent.mkdir(parents=True, exist_ok=True)
        out.save(dst)
    except Exception as e:
        return {"ok": False, "path": str(dst), "used_base": used_base, "legacy": not used_base,
                "reason": f"합성 실패: {e}"}
    if mark:
        scene = {"content": text}
        script_store.mark_overlay_applied([idx], current_key(scene, cfg, idx=idx))
    return {"ok": True, "path": str(dst), "used_base": used_base, "legacy": not used_base,
            "chars": len(text or ""), "scene": idx}


def apply_all(script: list = None, cfg: dict = None, only=None, log=print) -> dict:
    """여러 장면 텍스트 합성. only = 장면 번호 목록(1부터), None=전체"""
    script = script if script is not None else script_store.load_script_file()
    cfg = cfg or load_config()
    if not script:
        return {"ok": False, "count": 0, "reason": "대본(script.txt)이 없습니다."}
    targets = [int(i) for i in only] if only else [i for i in range(1, len(script) + 1)]
    done, failed, legacy_used = 0, [], []
    ov_map = {}
    for i in targets:
        if not (1 <= i <= len(script)):
            continue
        text = script[i - 1].get("content", "") or ""
        if not text.strip():
            failed.append(i)
            continue
        res = apply_scene(i, text=text, cfg=cfg, mark=False)
        if res.get("ok"):
            done += 1
            ov_map[str(i)] = current_key({"content": text}, cfg, idx=i)
            if res.get("legacy"):
                legacy_used.append(i)
            log(f"   💬 장면 {i:02d} 텍스트 합성 완료 ({'원본' if res.get('used_base') else '기존 에어리어 덮기'})")
        else:
            failed.append(i)
            log(f"   ⚠ 장면 {i:02d} 합성 실패: {res.get('reason')}")
    if ov_map:
        script_store.mark_overlay_applied_map(ov_map)
    return {"ok": True, "count": done, "failed": failed, "legacy": legacy_used}


def sync_missing_bases(script=None) -> dict:
    """base 원본이 비어 있는 장면은 현재 완성 이미지를 base로 복사해 보존한다.

    웹 편집기(webapp.main) 시작 시 자동 실행 —
    교체/삽입/그리기로 만든 이미지가 프로그램 재시작 후 옛 상태로
    되돌아가는 현상을 막는다. base가 이미 있는 장면은 건드리지 않는다.
    """
    if script is None:
        try:
            script = script_store.load_script_file()
        except Exception:
            script = []
    saved, missing = [], []
    if script:
        idxs = list(range(1, len(script) + 1))
    else:
        # 대본이 비어 있으면 이미지 파일명에서 장면 번호를 유추
        idxs = []
        d = final_path(1).parent
        if d.exists():
            for f in d.glob("scene_*.png"):
                head = f.stem.replace("scene_", "", 1)
                if head.isdigit():
                    idxs.append(int(head))
        idxs = sorted(idxs)
    for i in idxs:
        b, f = base_path(i), final_path(i)
        if b.exists():
            continue
        if not f.exists():
            missing.append(i)
            continue
        # 생성 실패 의심(단색 등) 이미지는 원본으로 굳히지 않는다
        suspect, _why = is_suspect_image(f)
        if suspect:
            missing.append(i)
            continue
        try:
            save_base_from(f, i, overwrite=False)
            saved.append(i)
        except Exception:
            missing.append(i)
    return {"ok": True, "saved": saved, "missing": missing}


def render_preview(idx, text: str = None, cfg: dict = None, max_w: int = 540) -> str:
    """웹 UI 미리보기용 축소 이미지 생성 (원본 파일은 건드리지 않음)"""
    idx = int(idx)
    cfg = cfg or load_config()
    base, final = base_path(idx), final_path(idx)
    src = base if base.exists() else final
    if not src.exists():
        src = create_placeholder_base(idx)
    text = _scene_content(idx) if text is None else text
    try:
        img = Image.open(src).convert("RGB")
        W, H = img.size
        scale = min(1.0, float(max_w) / max(W, 1))
        small = img.resize((max(1, int(W * scale)), max(1, int(H * scale))), Image.LANCZOS)
        out = draw_text(small, text, cfg, scale=scale, legacy=not _is_base(src))
        # 이미지 삽입(박아 넣기) 미리보기 — 파일이 있으면 항상 표시
        ip = insert_path(idx)
        if ip.exists():
            try:
                ins_img = Image.open(ip)
                out = draw_insert(out, ins_img, cfg, scale=scale)
            except Exception:
                pass
        dst = preview_path(idx)
        out.save(dst)
        return str(dst)
    except Exception as e:
        print(f"⚠️ 미리보기 생성 실패 (장면 {idx}): {e}")
        return ""


def render_preview_all(script: list = None, cfg: dict = None, max_w: int = 540) -> list:
    script = script if script is not None else script_store.load_script_file()
    out = []
    for i in range(1, len(script or []) + 1):
        p = render_preview(i, cfg=cfg, max_w=max_w)
        if p:
            out.append(p)
    return out


def style_labels() -> dict:
    return {
        "bubble": "말풍선 (만화 스타일)",
        "caption": "자막 박스 (반투명 사각형)",
        "outline": "외곽선 글씨 (박스 없음)",
        "none": "표시 안 함",
    }


def position_labels() -> dict:
    return {"top": "상단", "middle": "중앙", "bottom": "하단"}


def frame_labels() -> dict:
    return {
        "rect": "일반 사각형",
        "rounded": "모서리 둥근 사각형",
        "tv": "TV 화면",
        "frame": "액자",
    }
