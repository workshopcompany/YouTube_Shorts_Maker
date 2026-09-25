# -*- coding: utf-8 -*-
"""대본(script.txt) · 체크포인트(checkpoint.json) 동기화 저장소

핵심 원칙
    1) `output/script.txt` 는 **사람이 수정하는 유일한 원본(source of truth)**
    2) 프로그램은 시작할 때 script.txt 를 읽어 체크포인트에 반영한다
       → 손으로 고친 대본이 '이어하기'에서 옛 내용으로 되살아나는 문제 제거
    3) 장면별 해시(서명)를 저장해 두고 비교해
       "이미지 다시 생성 / 텍스트만 다시 그리기 / 음성 다시 생성 / 영상 다시 만들기"
       대상 장면만 골라낸다 (API 재호출 없이 script.txt만 고쳐도 영상 제작 가능)

파일 구성 (output 폴더)
    script.txt          : 사람이 수정하는 대본
    checkpoint.json     : 이어하기용 진행 상태 (step + data.text_result.script)
    project_state.json  : 장면 서명 기록 (변경 감지 기준)
"""

from __future__ import annotations

import json
import hashlib
import re
import shutil
from datetime import datetime
from pathlib import Path

from config import OUTPUT_DIR

# ---- 경로 (테스트에서 set_output_dir() 로 교체 가능) ----
OUT = Path(OUTPUT_DIR)

SCRIPT_NAME = "script.txt"
CHECKPOINT_NAME = "checkpoint.json"
STATE_NAME = "project_state.json"


def set_output_dir(path) -> Path:
    """출력 폴더 변경 (테스트/다중 프로젝트용)"""
    global OUT
    OUT = Path(path)
    return OUT


def out_dir(ensure: bool = True) -> Path:
    if ensure:
        OUT.mkdir(parents=True, exist_ok=True)
    return OUT


def script_path() -> Path:
    return out_dir() / SCRIPT_NAME


def checkpoint_path() -> Path:
    return out_dir() / CHECKPOINT_NAME


def state_path() -> Path:
    return out_dir() / STATE_NAME


def _now() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# 1) 대본 파싱 / 저장
# ============================================================
def parse_script_text(text: str) -> list:
    """script.txt 형식 텍스트를 대본 리스트로 복구.

    지원 형식 (괄호/대시/들여쓰기 차이 모두 허용):
        [장면 1] 0~5초
          내용: ...
          시각: ...
    """
    scenes = []
    cur = None
    for line in (text or "").split("\n"):
        m = re.match(r"\s*\[장면\s*(\d+)\]\s*(.*)", line)
        if m:
            if cur:
                scenes.append(cur)
            time_str = (m.group(2) or "").strip().strip("()").strip()
            cur = {"scene": int(m.group(1)), "time": time_str, "content": "", "visual": ""}
            continue
        if cur is None:
            continue
        cm = re.match(r"\s*-?\s*내용\s*:\s*(.*)", line)
        vm = re.match(r"\s*-?\s*시각\s*:\s*(.*)", line)
        if cm:
            cur["content"] = cm.group(1).strip()
        elif vm:
            cur["visual"] = vm.group(1).strip()
        elif line.strip():
            if cur["visual"]:
                cur["visual"] += " " + line.strip()
            elif cur["content"]:
                cur["content"] += " " + line.strip()
    if cur:
        scenes.append(cur)
    for i, sc in enumerate(scenes, 1):
        sc["scene"] = i
    # 빈 장면(내용·시각 모두 빈 값)도 보존한다.
    #  - 웹에서 '➕ 장면 추가'로 만든 빈 장면이 저장→로드 시 사라지던 버그 수정 (2026-09-23)
    #  - AI '빈 문구 채우기'의 대상이 유지되도록
    #  ([장면 N] 헤더가 없는 잡음은 cur 이 만들어지지 않으므로 여기서 따로 거르지 않는다)
    return scenes


def format_script_text(script: list) -> str:
    """대본 리스트 → script.txt 본문"""
    lines = []
    for i, scene in enumerate(script or [], 1):
        num = scene.get("scene") or i
        lines.append(f"[장면 {num}] {scene.get('time', '')}")
        lines.append(f"  내용: {scene.get('content', '')}")
        lines.append(f"  시각: {scene.get('visual', '')}")
        lines.append("")
    return "\n".join(lines)


def load_script_file() -> list:
    """script.txt 읽어서 대본 리스트 반환 (없으면 빈 리스트)"""
    p = script_path()
    if not p.exists():
        return []
    try:
        return parse_script_text(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️ script.txt 읽기 실패: {e}")
        return []


def save_script_file(script: list, backup: bool = True) -> str:
    """대본을 script.txt 로 저장 (수정 전 내용은 script.txt.bak 로 보관)"""
    p = script_path()
    if backup and p.exists():
        try:
            shutil.copyfile(p, p.with_suffix(".txt.bak"))
        except Exception:
            pass
    p.write_text(format_script_text(script), encoding="utf-8")
    # 편집 시각 기록 → 체크포인트보다 최신인지 판단에 사용
    return str(p)


def script_mtime() -> float:
    p = script_path()
    return p.stat().st_mtime if p.exists() else 0.0


def load_text_files() -> tuple:
    """titles.txt / title.txt / description.txt 복구. 반환 (titles, description)"""
    titles, description = [], ""
    f = out_dir() / "titles.txt"
    if f.exists():
        for ln in f.read_text(encoding="utf-8").split("\n"):
            ln = ln.strip()
            if ln:
                titles.append(re.sub(r"^\d+\.\s*", "", ln))
    f = out_dir() / "title.txt"
    if f.exists() and not titles:
        t = f.read_text(encoding="utf-8").strip()
        if t:
            titles = [t]
    f = out_dir() / "description.txt"
    if f.exists():
        description = f.read_text(encoding="utf-8").strip()
    return titles, description


def restore_saved_files() -> tuple:
    """저장 파일에서 작업 복구. 반환 (titles, description, script)"""
    titles, description = load_text_files()
    return titles, description, load_script_file()


# ============================================================
# 2) 체크포인트 (이어하기 상태)
# ============================================================
def load_checkpoint():
    p = checkpoint_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"⚠️ 체크포인트 읽기 실패: {e}")
    return None


def save_checkpoint(step, data, quiet: bool = False):
    out_dir()
    p = checkpoint_path()
    p.write_text(json.dumps({"step": step, "data": data}, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    if not quiet:
        print(f"💾 체크포인트 저장 완료 (단계 {step})")
    return str(p)


def clear_checkpoint():
    p = checkpoint_path()
    if p.exists():
        p.unlink()


def checkpoint_script() -> list:
    ck = load_checkpoint() or {}
    tr = (ck.get("data") or {}).get("text_result") or {}
    return tr.get("script") or []


# ============================================================
# 3) 장면 서명(해시) — 변경 감지 기준
# ============================================================
def content_hash(text: str) -> str:
    return hashlib.md5((text or "").strip().encode("utf-8")).hexdigest()[:16]


def scene_signature(scene: dict) -> dict:
    """장면 하나의 서명 = 내용/시각 각각의 해시"""
    return {
        "content": content_hash(scene.get("content", "")),
        "visual": content_hash(scene.get("visual", "")),
    }


def signature_list(script: list) -> list:
    return [scene_signature(sc) for sc in (script or [])]


def _range_text(nums: list) -> str:
    """[1,2,3,7] → '1~3, 7'"""
    if not nums:
        return "-"
    nums = sorted(nums)
    groups, start, prev = [], nums[0], nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        groups.append((start, prev))
        start = prev = n
    groups.append((start, prev))
    return ", ".join(f"{a}~{b}" if b > a else f"{a}" for a, b in groups)


def diff_scripts(old: list, new: list) -> dict:
    """장면별 차이 계산 (1부터 시작하는 장면 번호)"""
    old = old or []
    new = new or []
    res = {
        "count_changed": len(old) != len(new),
        "content_changed": [],
        "visual_changed": [],
        "added": [],
        "removed": [],
    }
    n = min(len(old), len(new))
    for i in range(n):
        a, b = scene_signature(old[i]), scene_signature(new[i])
        if a["visual"] != b["visual"]:
            res["visual_changed"].append(i + 1)
        if a["content"] != b["content"]:
            res["content_changed"].append(i + 1)
    res["added"] = list(range(n + 1, len(new) + 1))
    res["removed"] = list(range(n + 1, len(old) + 1))
    return res


def diff_summary(diff: dict) -> str:
    """사람이 읽기 쉬운 변경 요약"""
    if not diff:
        return "변경 없음"
    parts = []
    if diff.get("visual_changed"):
        parts.append(f"시각 변경 {_range_text(diff['visual_changed'])} (이미지 재생성 필요)")
    if diff.get("content_changed"):
        parts.append(f"대사 변경 {_range_text(diff['content_changed'])} (텍스트·음성 다시 만들기)")
    if diff.get("added"):
        parts.append(f"추가된 장면 {_range_text(diff['added'])}")
    if diff.get("removed"):
        parts.append(f"삭제된 장면 {_range_text(diff['removed'])}")
    if diff.get("count_changed") and not (diff.get("added") or diff.get("removed")):
        parts.append(f"장면 수 변경 {len(diff.get('added') or [])}")
    if not parts:
        parts.append("내용 동일")
    return " / ".join(parts)


# ============================================================
# 4) 프로젝트 상태 (장면 서명 기록) — 변경 감지 기준 저장소
# ============================================================
def load_state() -> dict:
    p = state_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(state: dict) -> dict:
    out_dir()
    state = dict(state or {})
    state["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    state_path().write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def has_hanja(text: str) -> bool:
    """한자(CJK) 포함 여부 — TTS 오발음·어색한 표기 감지용 (main.py 와 동일 기준)"""
    return any('\u4e00' <= ch <= '\u9fff' or '\u3400' <= ch <= '\u4dbf'
               for ch in (text or ""))


def update_scene_signatures(script: list, state: dict = None) -> dict:
    """현재 대본의 서명을 기록 (scene_sig = '지금 대본' 기준)"""
    st = dict(state if state is not None else load_state())
    st["scene_sig"] = signature_list(script)
    st["scene_count"] = len(script or [])
    return save_state(st)


def mark_assets(script: list, kinds=("img", "audio", "video"), indices=None, state: dict = None) -> dict:
    """지정한 작업(이미지/음성/영상)이 '현재 대본 기준으로 완료됨'을 기록.

    indices: 1부터 시작하는 장면 번호 목록 (None=전체)
    """
    st = dict(state if state is not None else load_state())
    sig = signature_list(script)
    for kind in kinds:
        key = f"{kind}_sig"
        prev = list(st.get(key) or [])
        if len(prev) < len(sig):
            prev = prev + [None] * (len(sig) - len(prev))
        elif len(prev) > len(sig):
            prev = prev[:len(sig)]
        for i in range(len(sig)):
            scene_no = i + 1
            if indices is None or scene_no in indices:
                # 실제로 파일이 디스크에 존재할 때만 완료 서명을 기록
                if kind == "img" and not scene_image_path(scene_no).exists():
                    prev[i] = None
                elif kind == "audio" and not scene_audio_path(scene_no).exists():
                    prev[i] = None
                else:
                    prev[i] = sig[i]
        st[key] = prev
    st["scene_sig"] = sig
    st["scene_count"] = len(script or [])
    return save_state(st)


def mark_overlay_applied(indices, key: str, state: dict = None) -> dict:
    """텍스트(말풍선/자막) 합성 완료 기록: {장면번호: 해시}"""
    st = dict(state if state is not None else load_state())
    ov = dict(st.get("overlay_sig") or {})
    for i in indices:
        ov[str(i)] = key
    st["overlay_sig"] = ov
    return save_state(st)


def mark_overlay_applied_map(mapping: dict, state: dict = None) -> dict:
    """{장면번호: 해시} 일괄 기록 (장면마다 대사가 달라 해시가 다를 때)"""
    if not mapping:
        return state if state is not None else load_state()
    st = dict(state if state is not None else load_state())
    ov = dict(st.get("overlay_sig") or {})
    for k, v in mapping.items():
        ov[str(k)] = v
    st["overlay_sig"] = ov
    return save_state(st)


def mark_video_built(script: list, video_path: str, state: dict = None) -> dict:
    st = dict(state if state is not None else load_state())
    st["video_sig"] = signature_list(script)
    st["video_path"] = video_path
    return save_state(st)


def ensure_baseline_from_checkpoint(old_script: list = None, state: dict = None) -> dict:
    """변경 감지 기준이 없을 때, 체크포인트의 (마지막으로 사용한) 대본을 기준으로 삼는다."""
    st = dict(state if state is not None else load_state())
    if st.get("img_sig") or st.get("audio_sig") or st.get("video_sig"):
        return st
    old_script = old_script if old_script is not None else checkpoint_script()
    if not old_script:
        return st
    sig = signature_list(old_script)
    st.setdefault("img_sig", sig)
    st.setdefault("audio_sig", sig)
    st.setdefault("video_sig", sig)
    st["baseline_source"] = "checkpoint"
    return save_state(st)


# ============================================================
# 5) 장면 파일 경로 / 상태 / 작업 계획
# ============================================================
def scene_image_path(idx) -> Path:
    return out_dir() / "images" / f"scene_{int(idx):02d}.png"


def scene_base_path(idx) -> Path:
    """텍스트(말풍선)를 그리기 전 원본 이미지 (API 재호출 없이 텍스트만 다시 그리기용)"""
    return out_dir() / "images" / "base" / f"scene_{int(idx):02d}.png"


def scene_audio_path(idx) -> Path:
    return out_dir() / "audio" / f"scene_{int(idx):02d}.mp3"


def scene_status(script: list = None, state: dict = None, overlay_key=None) -> list:
    """장면별 자산 상태 목록 (웹 UI/CLI 공용)

    overlay_key: 장면 dict → 현재 텍스트 합성 해시를 돌려주는 함수(선택).
                 modules.overlay.current_key 를 넘기면 '설정 변경'까지 감지한다.
                 (idx=장면번호 키워드까지 받으면 삽입 이미지·삽입 설정 변경도 감지)
    """
    script = script if script is not None else load_script_file()
    st = state if state is not None else load_state()
    sig = signature_list(script)
    img_sig = list(st.get("img_sig") or [])
    aud_sig = list(st.get("audio_sig") or [])
    ov_sig = dict(st.get("overlay_sig") or {})
    rows = []
    for i, sc in enumerate(script, 1):
        s = sig[i - 1]
        img, base, aud = scene_image_path(i), scene_base_path(i), scene_audio_path(i)
        prev_img = img_sig[i - 1] if i - 1 < len(img_sig) else None
        prev_aud = aud_sig[i - 1] if i - 1 < len(aud_sig) else None
        visual_changed = (not img.exists()) or (not prev_img) or prev_img.get("visual") != s["visual"]
        content_changed = (not img.exists()) or (not prev_img) or prev_img.get("content") != s["content"]
        # 음성은 '음성 기준(audio_sig)'과 비교 — 음성만 다시 만들어도 기준이 갱신되어
        # 불필요한 재생성이 반복되지 않는다.
        audio_changed = (not aud.exists()) or (not prev_aud) or prev_aud.get("content") != s["content"]
        ov_key = None
        if overlay_key is not None:
            try:
                ov_key = overlay_key(sc, idx=i)      # 삽입 이미지·삽입 설정까지 감지
            except TypeError:
                try:
                    ov_key = overlay_key(sc)         # 1-인자 콜백 호환
                except Exception:
                    ov_key = None
            except Exception:
                ov_key = None
        overlay_changed = (ov_key is not None and ov_sig.get(str(i)) not in (None, ov_key))
        rows.append({
            "scene": i,
            "time": sc.get("time", ""),
            "content": sc.get("content", ""),
            "visual": sc.get("visual", ""),
            "image_exists": img.exists(),
            "base_exists": base.exists(),
            "audio_exists": aud.exists(),
            "visual_changed": bool(visual_changed),
            "content_changed": bool(content_changed),
            "audio_changed": bool(audio_changed),
            "overlay_changed": bool(overlay_changed),
        })
    return rows


def plan_tasks(script: list = None, state: dict = None, overlay_key=None) -> dict:
    """변경된 부분만 다시 만들기 위한 작업 계획.

    image_regen  : 시각(visual)이 바뀜/이미지 없음 → 이미지 다시 생성 (로컬 SD 등)
    image_overlay: 대사만 바뀜 → base 이미지에 텍스트만 다시 그리면 됨 (무료·즉시)
    audio_regen  : 대사가 바뀜/음성 없음 → TTS 다시 생성 (무료 edge-tts)
    video_stale  : 위 작업이 있거나 대본이 바뀜 → 영상 다시 만들기
    """
    script = script if script is not None else load_script_file()
    st = state if state is not None else load_state()
    rows = scene_status(script, st, overlay_key=overlay_key)
    plan = {
        "baseline": bool(st.get("img_sig") or st.get("audio_sig") or st.get("video_sig")),
        "scene_count": len(script or []),
        "saved_scene_count": st.get("scene_count"),
        "image_regen": [],
        "image_overlay": [],
        "image_ok": [],
        "audio_regen": [],
        "audio_ok": [],
        "video_stale": False,
        "rows": rows,
    }
    for r in rows:
        i = r["scene"]
        if (not r["image_exists"]) or r["visual_changed"]:
            plan["image_regen"].append(i)
        elif r["content_changed"] or r["overlay_changed"]:
            plan["image_overlay"].append(i)
        else:
            plan["image_ok"].append(i)
        if (not r["audio_exists"]) or r["audio_changed"]:
            plan["audio_regen"].append(i)
        else:
            plan["audio_ok"].append(i)

    need_video = bool(plan["image_regen"] or plan["image_overlay"] or plan["audio_regen"])
    if not need_video:
        vsig = st.get("video_sig") or []
        need_video = (vsig != signature_list(script)) or (not st.get("video_path"))
    plan["video_stale"] = bool(need_video)
    plan["summary"] = plan_summary(plan)
    return plan


def plan_summary(plan: dict) -> str:
    lines = []
    if not plan.get("baseline"):
        lines.append("• 변경 감지 기준 없음 → '전체'로 한 번 제작하면 다음부터 변경분만 계산됩니다")
    lines.append(f"• 이미지 다시 생성: {_range_text(plan.get('image_regen'))}"
                 + ("" if plan.get("image_regen") else " (없음)"))
    lines.append(f"• 텍스트만 다시 그리기: {_range_text(plan.get('image_overlay'))}"
                 + (" ← API 호출 없음, 즉시" if plan.get("image_overlay") else " (없음)"))
    lines.append(f"• 음성 다시 생성: {_range_text(plan.get('audio_regen'))}"
                 + (" ← edge-tts 무료" if plan.get("audio_regen") else " (없음)"))
    lines.append("• 영상 다시 만들기: " + ("필요" if plan.get("video_stale") else "불필요"))
    return "\n".join(lines)


# ============================================================
# 6) script.txt → 체크포인트 동기화
# ============================================================
def sync_script_to_checkpoint(create: bool = True, apply: bool = True) -> dict:
    """script.txt 를 읽어 체크포인트와 비교하고, 다르면 체크포인트에 반영한다.

    반환:
        {"script": [...], "count": n, "changed": bool, "applied": bool,
         "diff": {...}, "summary": "...", "checkpoint_step": step|None,
         "created": bool, "message": "..."}
    """
    script = load_script_file()
    report = {
        "script": script, "count": len(script), "changed": False, "applied": False,
        "diff": None, "summary": "", "checkpoint_step": None, "created": False,
        "message": "",
    }
    if not script:
        report["message"] = "script.txt 가 없거나 비어 있습니다."
        return report

    ck = load_checkpoint()
    if ck is None:
        if not create:
            report["message"] = "체크포인트 없음 (script.txt 만 존재)"
            return report
        titles, description = load_text_files()
        data = {
            "idea": "(script.txt 에서 복구)",
            "text_result": {"titles": titles, "description": description, "script": script},
            "restored_from": "script.txt",
        }
        if apply:
            save_checkpoint(0, data)
        update_scene_signatures(script)
        report.update(changed=True, applied=apply, created=True, checkpoint_step=0,
                      summary="체크포인트를 script.txt 내용으로 새로 만들었습니다.")
        return report

    data = dict(ck.get("data") or {})
    tr = dict(data.get("text_result") or {})
    old_script = tr.get("script") or []
    diff = diff_scripts(old_script, script)
    changed = bool(diff["count_changed"] or diff["content_changed"] or diff["visual_changed"])
    report.update(diff=diff, changed=changed, checkpoint_step=ck.get("step"),
                  summary=diff_summary(diff))

    # 이전 제작 기록(체크포인트 대본)을 '변경 감지 기준'으로 확보
    ensure_baseline_from_checkpoint(old_script)

    if changed and apply:
        tr["script"] = script
        data["text_result"] = tr
        data["script_synced_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for key in ("image_paths", "audio_paths"):   # 장면 수가 줄면 잘라내기
            if isinstance(data.get(key), list) and len(data[key]) > len(script):
                data[key] = data[key][:len(script)]
        save_checkpoint(ck.get("step", 0), data)
        update_scene_signatures(script)
        report["applied"] = True
    return report
