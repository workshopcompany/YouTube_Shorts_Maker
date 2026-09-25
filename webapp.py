# -*- coding: utf-8 -*-
"""로컬 웹 편집기 (표준 라이브러리만 사용 — 추가 설치 불필요)

    • script.txt 대본 편집 → 저장하면 체크포인트에 즉시 동기화
    • 대사를 생성 이미지에 '붙여넣기': 말풍선/자막/외곽선 + 위치·크기·색 조절 + 실시간 미리보기
    • 변경된 장면만 골라 이미지 / 텍스트 / 음성 / 영상 다시 만들기
    • 진행 로그 실시간 표시 (백그라운드 작업)

실행
    start_web.bat
    (또는) .\\venv\\Scripts\\python.exe -X utf8 webapp.py
    브라우저: http://127.0.0.1:8765
"""

from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import OUTPUT_DIR, VIDEO_PLAYBACK_SPEED, VIDEO_WIDTH, VIDEO_HEIGHT  # noqa: E402
from modules import script_store, overlay as overlay_mod, pipeline  # noqa: E402

HOST = os.environ.get("WEBAPP_HOST", "127.0.0.1")
PORT = int(os.environ.get("WEBAPP_PORT", "8765"))
WEB_DIR = ROOT / "webui"
JOB_LOG = Path(OUTPUT_DIR) / "web_job.log"
JOB_SPEC = Path(OUTPUT_DIR) / "web_job_spec.json"
MAX_LOG_CHARS = 40000

JOB = {"proc": None, "started": None, "label": ""}
LOCK = threading.Lock()


# ============================================================
# 상태 / 미디어 유틸
# ============================================================
def media_url(path) -> str:
    """프로젝트 폴더 기준 상대경로 → /media URL (캐시 무효화용 mtime 포함)

    격리 모드(SAAS_OUTPUT_DIR)로 output 이 프로젝트 밖이면 out=1 표시로 제공한다."""
    if not path:
        return ""
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    if not p.exists():
        return ""
    v = int(p.stat().st_mtime)
    try:
        rel = p.resolve().relative_to(ROOT.resolve()).as_posix()
        return f"/media?path={urllib.parse.quote(rel)}&v={v}"
    except ValueError:
        pass
    try:
        rel = p.resolve().relative_to(Path(OUTPUT_DIR).resolve()).as_posix()
        return f"/media?out=1&path={urllib.parse.quote(rel)}&v={v}"
    except ValueError:
        return ""


def get_preview(idx: int, cfg: dict = None, force: bool = False) -> str:
    """장면 미리보기(축소 이미지) 경로. 캐시가 유효하면 재사용."""
    idx = int(idx)
    src = overlay_mod.base_path(idx)
    if not src.exists():
        src = overlay_mod.final_path(idx)
    if not src.exists():
        return ""
    dst = overlay_mod.preview_path(idx)
    cfg = cfg or overlay_mod.load_config()
    cfg_mtime = overlay_mod.config_path().stat().st_mtime if overlay_mod.config_path().exists() else 0
    if (not force and dst.exists()
            and dst.stat().st_mtime >= max(src.stat().st_mtime, cfg_mtime)):
        return str(dst)
    return overlay_mod.render_preview(idx, cfg=cfg)


def _torch_available() -> bool:
    """로컬 SD 이미지 생성이 가능한 파이썬인지 (venv 파이썬 = True)"""
    import importlib.util
    try:
        return importlib.util.find_spec("torch") is not None
    except Exception:
        return False


def build_state(force_preview: bool = False) -> dict:
    script = script_store.load_script_file()
    cfg = overlay_mod.load_config()
    state = script_store.load_state()
    plan = script_store.plan_tasks(script, state, overlay_key=overlay_mod.current_key)
    rows = plan.pop("rows")
    titles, description = script_store.load_text_files()
    ck = script_store.load_checkpoint() or {}

    for r in rows:
        i = r["scene"]
        r["preview_url"] = media_url(get_preview(i, cfg, force=force_preview))
        r["image_url"] = media_url(script_store.scene_image_path(i))
        r["audio_url"] = media_url(script_store.scene_audio_path(i))
        ip = overlay_mod.insert_path(i)
        r["insert_exists"] = ip.exists()
        r["insert_url"] = media_url(ip) if ip.exists() else ""
        # 한자 감지 — TTS 오발음·어색한 표기 경고용 (main.py 의 ⚠️ 표시와 동일)
        r["has_hanja"] = script_store.has_hanja(r.get("content") or "") \
            or script_store.has_hanja(r.get("visual") or "")
        # 원본(base) 품질 플래그 — 단색(생성 실패) 이미지면 UI에서 경고 표시
        bp = overlay_mod.base_path(i)
        if bp.exists():
            _sus, _why = overlay_mod.is_suspect_image(bp)
            r["base_suspect"] = _sus
            r["base_suspect_reason"] = _why if _sus else ""
        else:
            r["base_suspect"] = False
            r["base_suspect_reason"] = ""
        # 임시 플레이스홀더 여부 — '아직 AI 이미지가 없음'을 UI에서 명확히 표시 (오해 방지)
        r["is_placeholder"] = overlay_mod.is_placeholder(i)

    return {
        "ok": True,
        "scenes": rows,
        "count": len(rows),
        "overlay": cfg,
        "styles": overlay_mod.style_labels(),
        "positions": overlay_mod.position_labels(),
        "frames": overlay_mod.frame_labels(),
        "plan": plan,
        "titles": titles,
        "description": description,
        "checkpoint": {"step": ck.get("step"), "exists": bool(ck)},
        "state_file": {"exists": script_store.state_path().exists(),
                       "updated": state.get("updated")},
        "image_modes": pipeline.IMAGE_MODES,
        "torch_available": _torch_available(),
        "default_speed": float(VIDEO_PLAYBACK_SPEED or 1.0),
        "paths": {
            "script": str(script_store.script_path()),
            "images": str(Path(OUTPUT_DIR) / "images"),
            "base": str(overlay_mod.base_dir()),
        },
        "job": job_status(include_log=False),
    }


# ============================================================
# 백그라운드 작업 실행/상태
# ============================================================
def job_status(include_log: bool = True) -> dict:
    with LOCK:
        proc = JOB.get("proc")
        running = bool(proc is not None and proc.poll() is None)
        rc = None if proc is None else proc.returncode
        info = {"running": running, "returncode": rc, "label": JOB.get("label") or "",
                "started": JOB.get("started")}
    if include_log:
        text = ""
        if JOB_LOG.exists():
            text = JOB_LOG.read_text(encoding="utf-8", errors="replace")
            if len(text) > MAX_LOG_CHARS:
                text = "…(앞부분 생략)…\n" + text[-MAX_LOG_CHARS:]
        info["log"] = text
    return info


def start_job(spec: dict, label: str = "") -> dict:
    with LOCK:
        proc = JOB.get("proc")
        if proc is not None and proc.poll() is None:
            return {"ok": False, "error": "이미 작업이 실행 중입니다."}

    # ---- 사전 점검: torch 없는 파이썬 서버에서는 로컬 SD 생성이 '조용히' 실패한다 ----
    # (증상: 🎨 새 이미지 만들기를 눌러도 이미지가 그대로 → 원인: 웹 편집기를 시스템 파이썬으로 실행)
    steps = spec.get("steps") or []
    mode = str(spec.get("image_mode") or "sd_gguf").lower()
    if "images" in steps and mode.startswith("sd"):
        import importlib.util as _ilu
        if _ilu.find_spec("torch") is None:
            return {
                "ok": False,
                "error": ("이 웹 편집기가 torch 없는 파이썬으로 실행 중이라 로컬 SD 이미지를 만들 수 없습니다. "
                          "창을 닫고 start_web.bat(venv 파이썬)으로 다시 실행하거나, 이미지 모델을 Gemini로 선택하세요."),
            }

    JOB_LOG.parent.mkdir(parents=True, exist_ok=True)
    JOB_SPEC.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    JOB_LOG.write_text("", encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    log_file = open(JOB_LOG, "a", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", "-X", "utf8", str(ROOT / "scripts" / "web_job.py"), str(JOB_SPEC)],
            cwd=str(ROOT), stdout=log_file, stderr=subprocess.STDOUT, env=env,
        )
    except Exception as e:
        log_file.close()
        return {"ok": False, "error": f"작업 실행 실패: {e}"}
    finally:
        # 자식 프로세스가 자체 핸들을 가지므로 부모 쪽 핸들은 닫아둔다 (핸들 누수 방지)
        try:
            log_file.close()
        except Exception:
            pass

    import datetime as _dt
    with LOCK:
        JOB.update({"proc": proc, "label": label,
                    "started": _dt.datetime.now().strftime("%H:%M:%S")})
    return {"ok": True, "pid": proc.pid, "label": label}


def stop_job() -> dict:
    with LOCK:
        proc = JOB.get("proc")
    if proc is None or proc.poll() is not None:
        return {"ok": False, "error": "실행 중인 작업이 없습니다."}
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


# ============================================================
# 액션
# ============================================================
def _clean_scenes(raw) -> list:
    scenes = []
    for sc in (raw or []):
        if not isinstance(sc, dict):
            continue
        scenes.append({
            "scene": len(scenes) + 1,
            "time": str(sc.get("time", "") or "").strip(),
            "content": str(sc.get("content", "") or "").strip(),
            "visual": str(sc.get("visual", "") or "").strip(),
        })
    return scenes


def save_script(scenes, sync: bool = True, titles=None, description=None) -> dict:
    """대본을 script.txt 로 저장하고 체크포인트에 동기화"""
    script = _clean_scenes(scenes)
    if not script:
        return {"ok": False, "error": "장면이 비어 있습니다."}
    script_store.save_script_file(script)
    # 새로 추가된 장면 등 이미지가 없는 장면에 기본 빈 플레이스홀더를 자동 생성 (깨짐 방지)
    for idx in range(1, len(script) + 1):
        if not overlay_mod.base_path(idx).exists() and not overlay_mod.final_path(idx).exists():
            overlay_mod.create_placeholder_base(idx)
    if titles is not None or description is not None:
        f_titles, f_desc = script_store.load_text_files()
        pipeline.save_text_files(titles if titles is not None else f_titles,
                                 description if description is not None else f_desc)
    report = script_store.sync_script_to_checkpoint(apply=sync) if sync else {}
    plan = script_store.plan_tasks(script, overlay_key=overlay_mod.current_key)
    plan.pop("rows", None)
    applied = bool(report.get("applied"))
    return {
        "ok": True,
        "count": len(script),
        "sync": {"changed": report.get("changed"), "applied": applied,
                 "summary": report.get("summary"),
                 "checkpoint_step": report.get("checkpoint_step")},
        "plan": plan,
        "message": "script.txt 저장 + 체크포인트 반영 완료" if applied
                   else "script.txt 저장 완료 (체크포인트는 이미 최신)",
    }


def save_overlay(cfg: dict, apply_scope="none", scenes=None) -> dict:
    """overlay_config.json 저장 (+ 원하면 바로 적용)"""
    merged = overlay_mod.save_config(cfg or {})
    result = {"ok": True, "overlay": merged, "applied": None}
    if apply_scope in ("none", None, "skip"):
        return result
    script = script_store.load_script_file()
    if not script:
        result["ok"] = False
        result["error"] = "script.txt 가 없습니다."
        return result
    if apply_scope == "auto":
        idx = script_store.plan_tasks(script, overlay_key=overlay_mod.current_key)["image_overlay"]
    elif apply_scope == "all":
        idx = list(range(1, len(script) + 1))
    else:
        idx = pipeline._targets(script, scenes or [])
    if idx:
        result["applied"] = pipeline.render_overlays(script, idx, cfg=merged)
    else:
        result["applied"] = {"ok": True, "count": 0, "skipped": True}
    return result


def regen_audio(scenes=None, auto: bool = False) -> dict:
    """선택 장면(또는 변경분 전체)의 음성을 즉시 재생성하고 병합 음성도 갱신."""
    script = script_store.load_script_file()
    if not script:
        return {"ok": False, "error": "script.txt 가 없습니다."}
    if auto:
        plan = script_store.plan_tasks(script, overlay_key=overlay_mod.current_key)
        idx = plan["audio_regen"]
    else:
        idx = pipeline._targets(script, scenes)
    if not idx:
        return {"ok": True, "done": [], "failed": [], "merged": False,
                "skipped": True, "message": "다시 만들 음성이 없습니다. (모두 최신)"}
    res = pipeline.generate_audio(script, idx)
    merged = ""
    if res.get("done"):
        merged = pipeline.merge_audio(script)   # full_narration.mp3 갱신 → 영상에 새 음성 반영
    out = {"ok": bool(res.get("ok")), "done": res.get("done", []),
           "failed": res.get("failed", []), "merged": bool(merged)}
    if not out["ok"]:
        out["error"] = "음성 생성 실패 (네트워크/edge-tts 확인)"
    return out


def apply_overlay_now(scenes=None, cfg: dict = None) -> dict:
    script = script_store.load_script_file()
    if not script:
        return {"ok": False, "error": "script.txt 가 없습니다."}
    idx = pipeline._targets(script, scenes) if scenes else list(range(1, len(script) + 1))
    if not idx:
        return {"ok": False, "error": "대상 장면이 없습니다."}
    if cfg:
        # 미리보기에서 본 설정을 그대로 유지(저장) → 다음 열 때도 동일 스타일
        cfg = overlay_mod.save_config(cfg)
    return pipeline.render_overlays(script, idx, cfg=cfg)


def upload_base_image(scene: int, data_url: str) -> dict:
    """사용자가 올린 이미지를 해당 장면의 '원본(base)'으로 등록하고 대사를 그린다."""
    from PIL import Image
    m = re.match(r"data:image/[a-zA-Z0-9.+-]+;base64,(.+)", data_url or "", re.S)
    if not m:
        return {"ok": False, "error": "이미지 데이터(data URL) 형식이 아닙니다."}
    try:
        raw = base64.b64decode(m.group(1))
        img = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as e:
        return {"ok": False, "error": f"이미지 해석 실패: {e}"}

    idx = int(scene)
    target_w, target_h = int(VIDEO_WIDTH), int(VIDEO_HEIGHT)
    # 9:16 규격에 맞게 채우기(cover) 후 중앙 크롭
    sw, sh = img.size
    scale = max(target_w / sw, target_h / sh)
    new = img.resize((max(1, int(sw * scale)), max(1, int(sh * scale))), Image.LANCZOS)
    left = max(0, (new.width - target_w) // 2)
    top = max(0, (new.height - target_h) // 2)
    cropped = new.crop((left, top, left + target_w, top + target_h))

    # 원본 검증 — 단색/저분산이면 경고 (실수로 빈 이미지를 올리는 것 방지)
    suspect, why = overlay_mod.is_suspect_pil_image(cropped)
    warn = f"올린 이미지가 {why} — 원본 파일이 맞는지 확인하세요." if suspect else ""

    base = overlay_mod.base_path(idx)
    base.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(base)
    overlay_mod.clear_placeholder_flag(idx)   # 임시 표식 제거 (이제 실제 원본)

    res = overlay_mod.apply_scene(idx, cfg=overlay_mod.load_config())
    script = script_store.load_script_file()
    if 0 < idx <= len(script):
        script_store.mark_assets(script, kinds=("img",), indices=[idx])
    return {"ok": bool(res.get("ok")), "base": str(base), "image": res.get("path"),
            "warn": warn, "reason": res.get("reason")}


def upload_insert_image(scene: int, data_url: str) -> dict:
    """사용자 이미지를 해당 장면에 '박아 넣기'용으로 등록하고 즉시 합성 (교체 아님)"""
    from PIL import Image
    m = re.match(r"data:image/[a-zA-Z0-9.+-]+;base64,(.+)", data_url or "", re.S)
    if not m:
        return {"ok": False, "error": "이미지 데이터(data URL) 형식이 아닙니다."}
    try:
        raw = base64.b64decode(m.group(1))
        img = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as e:
        return {"ok": False, "error": f"이미지 해석 실패: {e}"}

    idx = int(scene)
    # 삽입 이미지 검증 — 빈/초소형 이미지는 삽입해도 보이지 않으므로 차단·경고
    if min(img.size) < 24:
        return {"ok": False,
                "error": f"삽입할 이미지가 너무 작습니다 ({img.size[0]}x{img.size[1]}). "
                         "원본 파일(캡처/첨부)을 확인하세요."}
    suspect, why = overlay_mod.is_suspect_pil_image(img)
    warn = f"삽입한 이미지가 {why} — 캡처/첨부가 빈 이미지가 아닌지 확인하세요." if suspect else ""
    ip = overlay_mod.insert_dir() / f"scene_{idx:02d}.png"
    ip.parent.mkdir(parents=True, exist_ok=True)
    img.save(ip)

    # 삽입 기능 자동 활성화 + 설정 저장
    cfg = overlay_mod.load_config()
    cfg["enabled"] = True
    overlay_mod.save_config(cfg)

    res = overlay_mod.apply_scene(idx, cfg=cfg)
    script = script_store.load_script_file()
    if 0 < idx <= len(script):
        script_store.mark_assets(script, kinds=("img",), indices=[idx])
    return {"ok": bool(res.get("ok")), "insert_url": media_url(ip),
            "image_url": media_url(res.get("path") or overlay_mod.final_path(idx)),
            "warn": warn, "reason": res.get("reason")}


def remove_insert_image(scene: int) -> dict:
    """장면에 삽입한 이미지를 제거하고 텍스트만 있는 상태로 되돌린다"""
    idx = int(scene)
    ip = overlay_mod.insert_path(idx)
    removed = False
    if ip.exists():
        ip.unlink()
        removed = True
    res = overlay_mod.apply_scene(idx, cfg=overlay_mod.load_config())
    return {"ok": True, "removed": removed,
            "image_url": media_url(res.get("path")) if res.get("ok") else ""}


def save_checkpoint_state(titles=None, description=None) -> dict:
    """현재 대본 + 이미지/음성 파일 상태를 체크포인트에 저장 (step 3까지 올림).

    웹에서 음성만 재생성한 뒤 체크포인트가 옛 상태여서
    다음 실행 때 옛 음성을 다시 만들/쓰는 문제를 방지한다.

    titles/description 가 전달되면 제목/설명 파일(titles.txt/title.txt/description.txt)도
    함께 갱신한다 — 웹 헤더의 "💾 상태 저장"으로 제목·설명 수정분을 반영할 수 있게.
    """
    # 제목/설명 먼저 저장 (script 가 없어도 제목 수정은 남도록)
    text_saved = False
    if titles is not None or description is not None:
        f_titles, f_desc = script_store.load_text_files()
        pipeline.save_text_files(titles if titles is not None else f_titles,
                                 description if description is not None else f_desc)
        text_saved = True

    script = script_store.load_script_file()
    if not script:
        return {"ok": False, "error": "script.txt 가 없습니다.",
                "titles_saved": text_saved}
    ck = script_store.load_checkpoint()
    data = dict((ck or {}).get("data") or {})
    tr = dict(data.get("text_result") or {})
    tr["script"] = script
    data["text_result"] = tr
    data["saved_from_web"] = True
    # 현재 디스크의 실제 존재하는 이미지/음성 경로만 체크포인트에 반영
    data["image_paths"] = [str(script_store.scene_image_path(i)) for i in range(1, len(script) + 1)
                           if script_store.scene_image_path(i).exists()]
    data["audio_paths"] = [str(script_store.scene_audio_path(i)) for i in range(1, len(script) + 1)
                           if script_store.scene_audio_path(i).exists()]
    step = max((ck or {}).get("step", 0), 3)
    script_store.save_checkpoint(step, data)
    # 변경 감지 기준 갱신 (실제 존재하는 파일만 서명됨)
    script_store.mark_assets(script, kinds=("img", "audio"))
    missing_audio = [i for i in range(1, len(script) + 1)
                     if not script_store.scene_audio_path(i).exists()]
    return {"ok": True, "step": step, "scenes": len(script),
            "missing_audio": missing_audio,
            "titles_saved": text_saved,
            "message": (f"체크포인트(step {step})에 현재 이미지·음성 상태를 저장했습니다."
                        + (" 제목·설명도 함께 저장했습니다." if text_saved else ""))}


def preview_scene(scene: int, text: str = None, cfg: dict = None, force: bool = True) -> dict:
    # 전달된 설정이 부분(예: 텍스트 슬라이더만)이어도 저장된 삽입 설정(enabled 등)이 유지되게 병합
    saved = overlay_mod.load_config()
    if cfg:
        saved.update(cfg)
        cfg = saved
    else:
        cfg = saved
    if text is not None:
        p = overlay_mod.render_preview(int(scene), text=text, cfg=cfg)
    else:
        p = get_preview(int(scene), cfg=cfg, force=force)
    return {"ok": bool(p), "url": media_url(p)}


# ============================================================
# HTTP 핸들러
# ============================================================
class Handler(BaseHTTPRequestHandler):
    server_version = "ShortsWebEditor/1.0"

    def log_message(self, fmt, *args):   # 콘솔 로그 최소화
        pass

    # ---- 응답 헬퍼 ----
    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _read_json(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            return json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            return {}

    def _file(self, path: Path, ctype: str = None):
        if not path.exists() or not path.is_file():
            self._json({"ok": False, "error": f"파일 없음: {path}"}, 404)
            return
        ctype = ctype or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self._send(200, path.read_bytes(), ctype)

    def _serve_media(self, rel: str, use_out: bool = False):
        rel = urllib.parse.unquote(rel or "")
        base = Path(OUTPUT_DIR).resolve() if use_out else ROOT.resolve()
        p = (base / rel).resolve()
        try:
            p.relative_to(base)
        except ValueError:
            self._json({"ok": False, "error": "허용되지 않은 경로"}, 403)
            return
        self._file(p)

    # ---- GET ----
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                self._file(WEB_DIR / "index.html", "text/html; charset=utf-8")
            elif u.path == "/favicon.ico":
                self._send(204, b"", "image/x-icon")
            elif u.path == "/api/state":
                self._json(build_state(force_preview=(q.get("force", ["0"])[0] == "1")))
            elif u.path == "/api/job":
                self._json(job_status())
            elif u.path == "/api/groq_models":
                # Groq 모델 목록 실시간 조회 (main.py select_text_api 의 모델 선택 이식)
                try:
                    from modules.text_gen import TextGenerator
                    models = TextGenerator.list_groq_models() or []
                    self._json({"ok": True, "models": models})
                except Exception as e:
                    self._json({"ok": False, "error": str(e), "models": []})
            elif u.path == "/api/plan":
                script = script_store.load_script_file()
                plan = script_store.plan_tasks(script, overlay_key=overlay_mod.current_key)
                plan.pop("rows", None)
                self._json({"ok": True, "plan": plan})
            elif u.path == "/media":
                self._serve_media(q.get("path", [""])[0],
                                  use_out=(q.get("out", ["0"])[0] == "1"))
            else:
                self._json({"ok": False, "error": "not found"}, 404)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._json({"ok": False, "error": str(e)}, 500)

    # ---- POST ----
    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        data = self._read_json()
        try:
            if u.path == "/api/script":
                res = save_script(data.get("scenes"), sync=data.get("sync", True),
                                  titles=data.get("titles"), description=data.get("description"))
            elif u.path == "/api/script_text":
                res = save_script(script_store.parse_script_text(data.get("text", "")))
            elif u.path == "/api/overlay":
                res = save_overlay(data.get("config") or {}, data.get("apply", "none"),
                                   data.get("scenes"))
            elif u.path == "/api/overlay/apply":
                res = apply_overlay_now(data.get("scenes"), data.get("config"))
            elif u.path == "/api/tts":
                res = regen_audio(data.get("scenes"), auto=bool(data.get("auto")))
            elif u.path == "/api/insert_image":
                if data.get("remove"):
                    res = remove_insert_image(int(data.get("scene", 1)))
                else:
                    res = upload_insert_image(int(data.get("scene", 1)), data.get("data_url", ""))
            elif u.path == "/api/save_state":
                res = save_checkpoint_state(titles=data.get("titles"),
                                            description=data.get("description"))
            elif u.path == "/api/preview":
                res = preview_scene(data.get("scene", 1), data.get("text"), data.get("config"))
            elif u.path == "/api/upload_image":
                res = upload_base_image(data.get("scene", 1), data.get("data_url", ""))
            elif u.path == "/api/run":
                res = start_job(data.get("spec") or {}, data.get("label", ""))
            elif u.path == "/api/job/stop":
                res = stop_job()
            else:
                self._json({"ok": False, "error": "not found"}, 404)
                return
            self._json(res)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._json({"ok": False, "error": str(e)}, 500)


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    port = PORT
    if "--port" in argv:
        try:
            port = int(argv[argv.index("--port") + 1])
        except Exception:
            pass

    # 테스트/다중 작업 격리 — 지정 시 실제 output 대신 이 폴더를 사용한다
    # (test_webapp.py 등이 실제 output 을 오염시키지 않도록)
    _env_out = os.environ.get("SAAS_OUTPUT_DIR")
    if _env_out:
        try:
            Path(_env_out).mkdir(parents=True, exist_ok=True)
            script_store.set_output_dir(_env_out)
            overlay_mod.OUTPUT_DIR = str(_env_out)
            global JOB_LOG, JOB_SPEC, OUTPUT_DIR
            JOB_LOG = Path(_env_out) / "web_job.log"
            JOB_SPEC = Path(_env_out) / "web_job_spec.json"
            OUTPUT_DIR = str(_env_out)
            print(f"📂 SAAS_OUTPUT_DIR 사용: {_env_out}")
        except Exception as e:
            print(f"⚠️ SAAS_OUTPUT_DIR 적용 실패: {e}")

    if not (WEB_DIR / "index.html").exists():
        print(f"❌ 웹 페이지를 찾을 수 없습니다: {WEB_DIR / 'index.html'}")
        return 1

    import importlib.util
    if importlib.util.find_spec("torch") is None:
        print("⚠️ 현재 파이썬에 torch 가 없어 '로컬 SD 이미지 생성'은 동작하지 않습니다.")
        print("   start_web.bat (venv 파이썬)으로 실행하면 정상 동작합니다.")

    # base 원본이 없는 장면은 현재 이미지를 원본으로 보존
    # (재시작 후 이미지가 옛 base 상태로 되돌아가는 현상 방지)
    try:
        _sync = overlay_mod.sync_missing_bases()
        if _sync.get("saved"):
            print(f"🖼 base 동기화: 장면 {_sync['saved']} → 원본으로 보존")
    except Exception as e:
        print(f"⚠️ base 동기화 실패: {e}")

    # ---- 단일 인스턴스 보장 ----
    # Windows 는 SO_REUSEADDR(ThreadingHTTPServer 기본값) 때문에 같은 포트에 서버가 2개 뜰 수 있고,
    # 그 경우 클릭/요청이 엉뚱한 서버(예: torch 없는 시스템 파이썬)로 가서
    # "이미지가 만들어지지 않는" 사고가 발생한다 → 두 번째 인스턴스는 명확히 거부한다.
    class _SingleInstanceHTTPServer(ThreadingHTTPServer):
        allow_reuse_address = False

    try:
        httpd = _SingleInstanceHTTPServer((HOST, port), Handler)
    except OSError:
        print("=" * 64)
        print(f"❌ 이미 웹 편집기가 실행 중입니다 (포트 {port} 사용 중).")
        print(f"   → 브라우저에서 http://{HOST}:{port}/ 를 열어 사용하세요.")
        print("   → 새로 시작하려면 기존 웹 편집기 창에서 Ctrl+C 로 종료 후 다시 실행하세요.")
        print("=" * 64)
        return 1
    url = f"http://{HOST}:{port}/"
    print("=" * 64)
    print("  🎬 유튜브 쇼츠 웹 편집기")
    print("=" * 64)
    print(f"  주소: {url}")
    print(f"  대본: {script_store.script_path()}")
    print(f"  원본 이미지 보관: {overlay_mod.base_dir()}")
    print("  종료: 이 창에서 Ctrl+C")
    print("=" * 64)
    if "--open" in argv or os.environ.get("WEBAPP_OPEN") == "1":
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n⏹️ 웹 편집기를 종료합니다.")
    finally:
        try:
            httpd.server_close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
