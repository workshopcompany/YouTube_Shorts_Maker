# -*- coding: utf-8 -*-
"""제작 파이프라인 (CLI / 웹 UI / 스크립트 공용)

단계별로 '필요한 장면만' 실행할 수 있게 분리했다.
    1) generate_images  : 장면 이미지 생성 (base 원본 보관 + 대사 텍스트 합성)
    2) render_overlays  : API 호출 없이 텍스트만 다시 그리기
    3) generate_audio   : 장면 음성 생성 (edge-tts, 무료)
    4) merge_audio      : 장면 음성 병합 (full_narration.mp3)
    5) build_video      : 이미지 + 음성 + 자막 → mp4
    6) execute_spec     : 위 단계를 JSON 스펙대로 실행 (웹 편집기 백그라운드 작업용)
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from config import (OUTPUT_DIR, SD_LOCAL_CHECKPOINT, SD_GGUF_CHECKPOINT,
                    VIDEO_PLAYBACK_SPEED)
from modules import script_store, overlay as overlay_mod

# 이미지 생성 방식
IMAGE_MODES = {
    "sd_gguf": "로컬 SD 3.5 Large Turbo (Q4 GGUF, 무료·API 없음)",
    "sd_sdxl": "로컬 SDXL-Turbo (무료·API 없음)",
    "gemini": "Gemini 이미지 API",
    "placeholder": "플레이스홀더 (테스트용)",
    "skip": "이미지 생성 건너뛰기",
}


# ------------------------------------------------------------
# 0) 공용 유틸
# ------------------------------------------------------------
def save_text_files(titles: list, description: str) -> None:
    """제목/설명 파일 저장 (titles.txt / title.txt / description.txt)"""
    out = Path(OUTPUT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    titles = titles or []
    with open(out / "titles.txt", "w", encoding="utf-8") as f:
        for i, t in enumerate(titles, 1):
            f.write(f"{i}. {t}\n")
    with open(out / "title.txt", "w", encoding="utf-8") as f:
        f.write(titles[0] if titles else "자동 생성 영상")
    with open(out / "description.txt", "w", encoding="utf-8") as f:
        f.write(description or "")


# 텍스트 생성 API 선택지 (main.py select_text_api 와 동일)
TEXT_APIS = {
    "gemini": "Gemini (기본)",
    "openrouter": "OpenRouter",
    "groq": "Groq (모델 목록에서 선택)",
}


def make_text_generator(api_key: str = "gemini", groq_model: str = None):
    """TextGenerator 생성 (초기화 실패 시 Gemini 폴백) — main.py create_text_gen 이식"""
    from modules.text_gen import TextGenerator
    try:
        return TextGenerator(api_type=api_key, groq_model=groq_model), api_key
    except Exception as e:
        print(f"⚠️ {api_key} 초기화 실패({e}) → Gemini 로 재시도")
        return TextGenerator(api_type="gemini"), "gemini"


def generate_text_content(idea: str, api: str = "gemini", groq_model: str = None,
                          character: str = None, title_mode: bool = True,
                          mode: str = "all", scene_index=None, log=print) -> dict:
    """아이디어 → 제목/설명/대본 생성 후 파일 저장 (main.py '단계 1'의 웹 이식)

    mode: "all"    = 제목+설명+대본 새로 생성 (기본)
          "script" = 기존 제목 유지, 대본만 새로 생성
          "fill"   = 현재 대본의 빈 내용/시각을 AI로 채움 (main 메뉴 5번)
          "scene"  = 지정 장면(scene_index)만 AI로 다시 작성 (main 메뉴 6번)
    - 결과: titles.txt/title.txt/description.txt/script.txt 갱신 + 체크포인트(step 1)
    """
    from config import MAIN_CHARACTER
    character = character or MAIN_CHARACTER
    text_gen, api_used = make_text_generator(api, groq_model)
    titles, description = script_store.load_text_files()

    if mode == "fill":
        base_script = script_store.load_script_file()
        if not base_script:
            return {"ok": False, "reason": "script.txt 가 비어 있습니다."}
        log("📝 빈 문구(내용/시각) 채우는 중...")
        script = text_gen.fill_empty_scenes(idea or "(빈 문구 채우기)", base_script,
                                            title_context=(titles or [None])[0],
                                            character=character)
    elif mode == "scene":
        base_script = script_store.load_script_file()
        if not base_script:
            return {"ok": False, "reason": "script.txt 가 비어 있습니다."}
        try:
            scene_no = int(scene_index)
        except (TypeError, ValueError):
            return {"ok": False, "reason": "장면 번호가 필요합니다."}
        if not (1 <= scene_no <= len(base_script)):
            return {"ok": False, "reason": f"장면 번호 범위 오류 (1~{len(base_script)})"}
        log(f"📝 장면 {scene_no} 다시 작성 중...")
        script = text_gen.regenerate_scene(idea or "(장면 다시 작성)", base_script, scene_no,
                                           title_context=(titles or [None])[0],
                                           character=character)
    else:
        idea = (idea or "").strip()
        if not idea:
            return {"ok": False, "reason": "아이디어를 입력하세요."}
        if (title_mode and mode == "all") or not titles:
            log(f"📝 제목/설명 생성 중... (API: {api_used})")
            titles = text_gen.generate_title(idea) or []
            description = text_gen.generate_description(idea) or ""
        log(f"📝 대본 생성 중... (제목반영, 주인공={character})")
        script = text_gen.generate_script(idea, title_context=(titles or [None])[0],
                                          character=character)

    if not script:
        return {"ok": False, "reason": "대본 생성/수정 실패 (0장면)"}

    save_text_files(titles, description)
    script_store.save_script_file(script)
    script_store.update_scene_signatures(script)
    script_store.save_checkpoint(1, {
        "idea": idea,
        "text_result": {"titles": titles, "description": description, "script": script},
        "character": character,
    })
    log(f"✅ 저장 완료: 제목 {len(titles)}개 / 대본 {len(script)}장면")
    return {"ok": True, "titles": titles, "description": description,
            "count": len(script), "api": api_used, "character": character}


def make_image_generator(mode_key: str):
    """이미지 생성기 생성. mode_key 는 IMAGE_MODES 키. skip 이면 None."""
    from modules.image_gen import ImageGenerator
    mode_key = (mode_key or "sd_gguf").lower()
    if mode_key in ("skip", "none"):
        return None
    if mode_key == "sd_gguf":
        return ImageGenerator(mode="sd_local", local_model_path=SD_GGUF_CHECKPOINT)
    if mode_key == "sd_sdxl":
        return ImageGenerator(mode="sd_local", local_model_path=SD_LOCAL_CHECKPOINT)
    if mode_key == "gemini":
        return ImageGenerator(mode="gemini")
    if mode_key == "placeholder":
        return ImageGenerator(mode="placeholder")
    raise ValueError(f"알 수 없는 이미지 방식: {mode_key}")


def _targets(script: list, indices=None) -> list:
    if not script:
        return []
    if indices is None:
        return list(range(1, len(script) + 1))
    if isinstance(indices, str):
        indices = [int(x) for x in re.findall(r"\d+", indices)]
    out = []
    for i in indices:
        try:
            i = int(i)
        except (TypeError, ValueError):
            continue
        if 1 <= i <= len(script):
            out.append(i)
    return sorted(set(out))


# ------------------------------------------------------------
# 1) 이미지 생성 (+ base 보관 + 대사 텍스트 합성)
# ------------------------------------------------------------
def generate_images(script: list = None, indices=None, mode_key: str = "sd_gguf",
                    cfg: dict = None, clear_stale: bool = True, log=print) -> dict:
    script = script if script is not None else script_store.load_script_file()
    targets = _targets(script, indices)
    res = {"ok": True, "mode": mode_key, "requested": targets, "done": [], "failed": []}
    if not targets:
        res["ok"] = False
        res["reason"] = "대상 장면이 없습니다."
        return res

    img_gen = make_image_generator(mode_key)
    if img_gen is None and mode_key not in ("skip", "none"):
        res["ok"] = False
        res["reason"] = f"이미지 생성기를 만들 수 없습니다: {mode_key}"
        return res
    if img_gen is None:
        log("   ⏭️ 이미지 생성 건너뜀")
        return res

    if clear_stale:
        # 대본 길이를 넘는 이전 작업 파일 정리 (장면-음성 어긋남 방지)
        for d in (Path(OUTPUT_DIR) / "images", Path(OUTPUT_DIR) / "images" / "base"):
            if not d.exists():
                continue
            for f in d.glob("scene_*.png"):
                try:
                    num = int(f.stem.split("_")[-1])
                except ValueError:
                    continue
                if num > len(script):
                    f.unlink()

    log(f"🎨 이미지 생성 시작: {len(targets)}장 (방식: {IMAGE_MODES.get(mode_key, mode_key)})")
    for i in targets:
        scene = script[i - 1]
        log(f"🎨 이미지 생성 중... [{i}/{len(script)}]")
        try:
            out = img_gen.generate_scene_images([scene], start_index=i)
            path = out[0] if out else None
        except KeyboardInterrupt:
            raise
        except Exception as e:
            path = None
            log(f"   ❌ 장면 {i} 오류: {e}")
        if path and os.path.exists(path):
            res["done"].append(i)
        else:
            res["failed"].append(i)
            log(f"   ⚠️ 장면 {i} 이미지 생성 실패")

    if res["done"]:
        script_store.mark_assets(script, kinds=("img",), indices=res["done"])
        # 이미지 생성 시 대사도 함께 그렸으므로 텍스트 합성 완료로 기록
        ov_cfg = cfg or overlay_mod.load_config()
        script_store.mark_overlay_applied_map(
            {str(i): overlay_mod.current_key(script[i - 1], ov_cfg, idx=i) for i in res["done"]})
    res["ok"] = bool(res["done"])
    log(f"✅ 이미지 완료: {len(res['done'])}장 / 실패 {len(res['failed'])}장")
    return res


# ------------------------------------------------------------
# 2) 텍스트만 다시 그리기 (API 없음)
# ------------------------------------------------------------
def render_overlays(script: list = None, indices=None, cfg: dict = None, log=print) -> dict:
    script = script if script is not None else script_store.load_script_file()
    targets = _targets(script, indices)
    if not targets:
        return {"ok": False, "count": 0, "reason": "대상 장면이 없습니다."}
    settings = cfg or overlay_mod.load_config()
    log(f"💬 텍스트 합성: {len(targets)}장 (스타일: {settings.get('style')} / 위치: {settings.get('position')})")
    return overlay_mod.apply_all(script, cfg=settings, only=targets, log=log)


# ------------------------------------------------------------
# 3) 음성 생성
# ------------------------------------------------------------
def generate_audio(script: list = None, indices=None, log=print) -> dict:
    from modules.tts import TTSEngine, current_voice
    script = script if script is not None else script_store.load_script_file()
    targets = _targets(script, indices)
    res = {"ok": True, "done": [], "failed": []}
    if not targets:
        res["ok"] = False
        res["reason"] = "대상 장면이 없습니다."
        return res

    tts = TTSEngine()
    log(f"   🗣 목소리: {current_voice()}")
    for i in targets:
        scene = script[i - 1]
        content = ((scene.get("content") or "").strip()
                   or (scene.get("visual") or "").strip() or f"장면 {i}")
        out_file = str(script_store.scene_audio_path(i))
        log(f"🎤 음성 생성 중... [{i}/{len(script)}]")
        try:
            result = tts.generate_speech_groq(content, out_file)
        except Exception as e:
            log(f"   ❌ 장면 {i} 음성 오류: {e}")
            result = None
        # 앞/뒤 무음 트리밍 (영상-음성 동기화 + 문장 간극 최소화)
        if result and os.path.exists(result):
            try:
                trimmed = tts.trim_silence(result)
                if trimmed and trimmed != result and os.path.exists(trimmed):
                    os.replace(trimmed, result)
            except Exception:
                pass
        if result and os.path.exists(result):
            res["done"].append(i)
            log(f"   ✅ 완료: {result}")
        else:
            res["failed"].append(i)
            log(f"   ⚠️ 장면 {i} 음성 생성 실패")

    if res["done"]:
        script_store.mark_assets(script, kinds=("audio",), indices=res["done"])
    res["ok"] = bool(res["done"])
    return res


def merge_audio(script: list = None, log=print) -> str:
    """장면 음성들을 full_narration.mp3 로 병합"""
    from modules.tts import TTSEngine
    script = script if script is not None else script_store.load_script_file()
    paths = [str(script_store.scene_audio_path(i)) for i in range(1, len(script) + 1)]
    paths = [p for p in paths if os.path.exists(p)]
    if not paths:
        log("   ⚠️ 병합할 음성이 없습니다.")
        return ""
    log(f"🎧 음성 병합: {len(paths)}개 장면")
    return TTSEngine().merge_audio_files(paths) or ""


# ------------------------------------------------------------
# 4) 영상 만들기
# ------------------------------------------------------------
def _safe_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "", str(name or "")).strip()
    return name or "final_video"


def build_video(script: list = None, titles: list = None, speed: float = None, log=print) -> dict:
    from modules.video_edit import VideoEditor
    from modules.image_gen import ensure_scene_images
    script = script if script is not None else script_store.load_script_file()
    if not script:
        return {"ok": False, "reason": "대본이 없습니다."}

    # 이미지: 대본 길이와 1:1 보장 (누락 장면은 임시 플레이스홀더로 대체)
    # → exists 필터로 목록이 짧아지면 n번째 자리에 n+1번 이미지가 들어와
    #   장면-음성-자막이 엇갈리고 '영상에 이미지가 빠지는' 문제가 생김
    images, missing_images = ensure_scene_images(script, log=log)
    if not images:
        return {"ok": False, "reason": "이미지가 없습니다. 먼저 이미지를 생성하세요."}

    # 음성: 경로 목록은 대본 길이와 1:1 유지 (누락은 measure_scene_durations가 평균으로 보정)
    # exists 필터를 하면 인덱스가 밀려 장면별 음성 길이가 어긋나므로 절대 필터하지 않음
    audio_paths = [str(script_store.scene_audio_path(i)) for i in range(1, len(script) + 1)]
    audio_missing = [i for i, p in enumerate(audio_paths, 1) if not os.path.exists(p)]
    if audio_missing:
        log(f"⚠️ 음성 없는 장면: {audio_missing} → 평균 길이로 대체")
    merged = Path(OUTPUT_DIR) / "audio" / "full_narration.mp3"
    full_audio = str(merged) if merged.exists() else (merge_audio(script, log=log) or None)

    editor = VideoEditor()
    durations = editor.measure_scene_durations(audio_paths, len(images), full_audio)
    scene_texts = [(s.get("content") or s.get("visual") or "") for s in script[:len(images)]]

    if titles is None:
        titles = script_store.load_text_files()[0]
    title = (titles or ["final_video"])[0]
    out_name = _safe_filename(title[:30]) + ".mp4"
    speed = float(speed if speed is not None else (VIDEO_PLAYBACK_SPEED or 1.0))

    log(f"🎬 영상 생성: 이미지 {len(images)}장 / 음성 {len(audio_paths)}개 / {speed}배속")
    video_path = editor.create_video_from_images(
        images, full_audio, output_file=out_name,
        scene_durations=durations, scene_texts=scene_texts, playback_speed=speed)
    if not video_path:
        log("⚠️ FFmpeg 실패 → MoviePy로 재시도")
        video_path = editor.create_video_with_moviepy(
            images, full_audio, output_file=out_name,
            scene_durations=durations, scene_texts=scene_texts, playback_speed=speed)
    if video_path:
        script_store.mark_video_built(script, video_path)
        log(f"✅ 영상 완료: {video_path}")
        return {"ok": True, "path": video_path}
    return {"ok": False, "reason": "영상 생성 실패"}


def upload_video(video_path=None, privacy: str = "private", titles=None,
                 description=None, title_index=0, log=print) -> dict:
    """유튜브 업로드 (main.py 단계 5와 동일 — modules.youtube_upload 재사용).

    - video_path 미지정 → output/videos 의 최신 mp4 자동 선택
    - privacy: "public"(공개) | "private"(비공개) | "unlisted"(링크 공개)
    - 최초 1회는 브라우저 구글 로그인(client_secrets.json → token.pickle)
    """
    from modules.youtube_upload import YouTubeUploader

    f_titles, f_desc = script_store.load_text_files()
    titles = titles if titles else f_titles
    description = description if description is not None else f_desc

    if not video_path or not os.path.exists(video_path):
        vd = Path(OUTPUT_DIR) / "videos"
        vids = sorted(vd.glob("*.mp4"), key=os.path.getmtime) if vd.exists() else []
        video_path = str(vids[-1]) if vids else None
    if not video_path:
        return {"ok": False, "reason": "업로드할 영상이 없습니다. 먼저 영상을 만드세요."}

    try:
        ti = int(title_index or 0)
    except (TypeError, ValueError):
        ti = 0
    if titles and 0 <= ti < len(titles):
        title = titles[ti]
    else:
        title = (titles or [None])[0] or Path(video_path).stem

    privacy = privacy if privacy in ("public", "private", "unlisted") else "private"
    label = {"public": "공개", "private": "비공개", "unlisted": "링크 공개"}[privacy]
    log(f"📤 유튜브 업로드: [{label}] {title}")
    log(f"   파일: {video_path}")
    try:
        uploader = YouTubeUploader()
        res = uploader.upload_video(video_path=video_path, title=title,
                                    description=description or "", privacy=privacy)
    except Exception as e:
        return {"ok": False, "reason": f"업로드 실패: {e}"}
    if isinstance(res, dict) and res.get("success"):
        log(f"🎉 업로드 완료: {res.get('url')}")
        return {"ok": True, "url": res.get("url"), "title": title,
                "privacy": res.get("privacy", privacy), "path": video_path}
    err = (res or {}).get("error") if isinstance(res, dict) else str(res)
    log(f"❌ 업로드 실패: {err}")
    return {"ok": False, "reason": err or "업로드 실패", "path": video_path}


# ------------------------------------------------------------
# 5) 작업 범위 해석 + 스펙 실행 (웹 편집기 백그라운드 작업)
# ------------------------------------------------------------
def _scope_indices(script: list, scope, auto_list) -> list:
    """scope: 'auto'(변경분) | 'all'(전체) | 'none' | [장면번호...]"""
    n = len(script or [])
    if scope in (None, "auto", "changed"):
        return list(auto_list or [])
    if scope in ("all", True):
        return list(range(1, n + 1))
    if scope in ("none", False, "skip"):
        return []
    return _targets(script, scope)


def execute_spec(spec: dict, log=print) -> dict:
    """JSON 스펙대로 제작 단계 실행.

    spec 예시:
        {
          "steps": ["images", "overlay", "tts", "video"],
          "scenes": {"images": "auto", "overlay": "auto", "tts": "auto"},
          "image_mode": "sd_gguf",
          "overlay": {...설정...},
          "speed": 1.3,
          "titles": ["..."], "description": "..."
        }
    """
    result = {"ok": True, "steps": {}, "sync": None}

    if spec.get("overlay"):
        overlay_mod.save_config(spec["overlay"])

    # ① script.txt → 체크포인트 동기화 (사용자가 고친 대본을 프로그램이 사용)
    report = script_store.sync_script_to_checkpoint(apply=True)
    script = report.get("script") or []
    result["sync"] = {"changed": report.get("changed"), "applied": report.get("applied"),
                      "summary": report.get("summary"), "count": len(script),
                      "checkpoint_step": report.get("checkpoint_step")}
    if not script:
        # text 단계가 포함되어 있으면(아이디어 → 새 대본 생성) 빈 대본으로도 진행
        if "text" in (spec.get("steps") or []):
            log("📝 script.txt 가 비어 있습니다 → text 단계에서 새 대본을 생성합니다.")
        else:
            result["ok"] = False
            result["reason"] = report.get("message") or "script.txt 가 비어 있습니다."
            log(f"❌ {result['reason']}")
            return result
    log(f"📌 대본 {len(script)}장면 (script.txt 기준)")
    if report.get("changed"):
        log(f"📝 script.txt 변경분을 체크포인트에 반영: {report.get('summary')}")

    # ② 제목/설명 저장 (웹에서 수정한 경우)
    if spec.get("titles") is not None or spec.get("description") is not None:
        f_titles, f_desc = script_store.load_text_files()
        save_text_files(spec.get("titles") or f_titles, spec.get("description", f_desc))

    steps = spec.get("steps") or ["overlay", "tts", "video"]
    scenes = spec.get("scenes") or {}
    try:
        plan = script_store.plan_tasks(script, overlay_key=overlay_mod.current_key)
    except Exception:
        plan = {"summary": f"대본 {len(script)}장면", "image_regen": [],
                "image_overlay": [], "audio_regen": []}
    log("📋 작업 계획\n" + (plan.get("summary") or ""))

    for step in steps:
        if step == "text":
            # 아이디어 → 제목/설명/대본 생성 · 빈 문구 채우기 · 장면 재작성 (main.py 단계 1의 웹 이식)
            res_text = generate_text_content(
                spec.get("idea", ""), spec.get("api", "gemini"),
                spec.get("groq_model"), spec.get("character"),
                title_mode=bool(spec.get("title_mode", True)),
                mode=spec.get("text_mode", "all"),
                scene_index=spec.get("scene_index"),
                log=log)
            result["steps"]["text"] = res_text
            if res_text.get("ok"):
                script = script_store.load_script_file()
                try:
                    plan = script_store.plan_tasks(script, overlay_key=overlay_mod.current_key)
                except Exception:
                    plan = {"summary": f"대본 {len(script)}장면 (새로 생성)",
                            "image_regen": [], "image_overlay": [], "audio_regen": []}
                log(f"📌 새 대본 {len(script)}장면으로 이후 단계를 진행합니다.")

        elif step == "images":
            idx = _scope_indices(script, scenes.get("images", "auto"), plan.get("image_regen"))
            if not idx:
                log("⏭️ 이미지: 대상 없음 (건너뜀)")
                result["steps"]["images"] = {"ok": True, "done": [], "skipped": True}
                continue
            result["steps"]["images"] = generate_images(
                script, idx, spec.get("image_mode", "sd_gguf"), log=log)

        elif step == "overlay":
            idx = _scope_indices(script, scenes.get("overlay", "auto"), plan.get("image_overlay"))
            if not idx:
                log("⏭️ 텍스트 합성: 대상 없음 (건너뜀)")
                result["steps"]["overlay"] = {"ok": True, "count": 0, "skipped": True}
                continue
            result["steps"]["overlay"] = render_overlays(script, idx, log=log)

        elif step == "tts":
            idx = _scope_indices(script, scenes.get("tts", "auto"), plan.get("audio_regen"))
            if idx:
                result["steps"]["tts"] = generate_audio(script, idx, log=log)
            else:
                log("⏭️ 음성: 대상 없음 (건너뜀)")
                result["steps"]["tts"] = {"ok": True, "done": [], "skipped": True}
            result["steps"]["merge"] = merge_audio(script, log=log)

        elif step == "video":
            result["steps"]["video"] = build_video(
                script, titles=spec.get("titles"), speed=spec.get("speed"), log=log)

        elif step == "upload":
            prev = result["steps"].get("video") or {}
            result["steps"]["upload"] = upload_video(
                video_path=spec.get("video_path") or (prev.get("path") if prev.get("ok") else None),
                privacy=spec.get("privacy", "private"),
                titles=spec.get("titles"),
                description=spec.get("description"),
                title_index=spec.get("title_index", 0),
                log=log)

        else:
            log(f"⚠️ 알 수 없는 단계: {step}")

    failed = [k for k, v in result["steps"].items()
              if isinstance(v, dict) and v.get("ok") is False]
    result["ok"] = not failed
    result["failed_steps"] = failed
    log("🎉 작업 완료" if result["ok"] else f"⚠️ 실패한 단계: {failed}")
    return result
