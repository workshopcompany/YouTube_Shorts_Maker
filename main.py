"""
YouTube 자동화 SaaS - 메인 실행 파일
원클릭으로 유튜브 쇼츠 영상 제작부터 업로드까지 자동화
"""

import os
import sys
import json
from pathlib import Path

# 모듈 경로 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from modules.text_gen import TextGenerator
from modules.image_gen import ImageGenerator, ensure_scene_images
from modules.tts import TTSEngine
from modules.video_edit import VideoEditor
from modules.youtube_upload import YouTubeUploader
from config import OUTPUT_DIR, SD_LOCAL_CHECKPOINT, SD_GGUF_CHECKPOINT, VIDEO_PLAYBACK_SPEED, MAIN_CHARACTER
from modules import script_store, overlay as overlay_mod, pipeline

# 체크포인트 파일 (script_store 와 같은 경로)
CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, "checkpoint.json")

def save_checkpoint(step, data):
    """진행 상황 저장 (modules/script_store 위임)"""
    return script_store.save_checkpoint(step, data)

def load_checkpoint():
    """이전 진행 상황 불러오기"""
    return script_store.load_checkpoint()

def clear_checkpoint():
    """체크포인트 삭제"""
    script_store.clear_checkpoint()


def parse_script_text(text: str) -> list:
    """script.txt 형식 텍스트를 대본 리스트로 복구 (modules/script_store 위임)

    지원 형식 (괄호/대시/들여쓰기 차이 모두 허용):
        [장면 1] 0~5초
          내용: ...
          시각: ...
    """
    return script_store.parse_script_text(text)


def restore_saved_files():
    """output 폴더의 저장 파일에서 작업 복구. 반환: (titles, description, script)"""
    return script_store.restore_saved_files()


def save_script_file(script: list, backup: bool = True):
    """대본을 script.txt로 저장 (이후 '저장된 파일에서 불러오기'로 재활용)"""
    path = script_store.save_script_file(script, backup=backup)
    script_store.update_scene_signatures(script)   # 변경 감지 기준 갱신
    print("✅ 대본 저장 완료: output/script.txt")
    return path


def clean_stale_scenes(script_len: int):
    """이전 실행 잔여 장면 파일 제거 (현재 대본 길이를 초과하는 scene_XX 파일)
    - 장면 수가 다른 이전 작업의 이미지/음성이 섞여 영상-음성이 어긋나는 것 방지"""
    out = Path(OUTPUT_DIR)
    removed = []
    for sub, pat in (("images", "scene_*.png"), ("audio", "scene_*.mp3")):
        d = out / sub
        if not d.exists():
            continue
        for f in d.glob(pat):
            try:
                num = int(f.stem.split("_")[-1])
            except ValueError:
                continue
            if num > script_len:
                removed.append(str(f))
                f.unlink()
    if removed:
        print(f"🧹 이전 작업 잔여 파일 {len(removed)}개 제거 (현재 대본 {script_len}장면 초과)")
        for r in removed[:5]:
            print(f"   - {r}")


def print_banner():
    """시작 배너 출력"""
    print("""
╔══════════════════════════════════════════════════════════════╗
║           🎬 YouTube 자동화 SaaS v1.0 🎬                    ║
║                                                              ║
║   원클릭으로 유튜브 쇼츠 영상 제작부터 업로드까지!           ║
╚══════════════════════════════════════════════════════════════╝
    """)


def print_step(step_num, total, message):
    """단계 출력"""
    print(f"\n{'='*60}")
    print(f"  📌 단계 [{step_num}/{total}]: {message}")
    print(f"{'='*60}")


def save_text_files(titles, description):
    """텍스트 파일 저장"""
    output_path = Path(OUTPUT_DIR)
    output_path.mkdir(parents=True, exist_ok=True)
    
    with open(output_path / "titles.txt", 'w', encoding='utf-8') as f:
        for i, title in enumerate(titles, 1):
            f.write(f"{i}. {title}\n")
    
    with open(output_path / "title.txt", 'w', encoding='utf-8') as f:
        f.write(titles[0] if titles else "자동 생성 영상")
    
    with open(output_path / "description.txt", 'w', encoding='utf-8') as f:
        f.write(description)
    
    print("✅ 텍스트 파일 저장 완료")

def edit_text_list(items: list, label: str = "항목") -> list:
    """제목 리스트 간단 수정. 번호 입력 후 새 문구, 엔터만 치면 유지, 0 입력 시 종료."""
    print(f"\n✏️ {label} 수정 (번호 입력 → 새 문구, 엔터 유지, 0 종료)")
    items = list(items)
    while True:
        for i, t in enumerate(items, 1):
            print(f"   {i}. {t}")
        sel = input(f"\n수정할 번호 (0=종료): ").strip()
        if sel == "0" or sel == "":
            break
        try:
            idx = int(sel) - 1
            if 0 <= idx < len(items):
                new = input(f"새 {label} (엔터=유지): ").strip()
                if new:
                    items[idx] = new
                    print("   ✅ 수정됨")
        except ValueError:
            print("   숫자를 입력하세요.")
    return items


def edit_text_block(text: str, label: str = "설명문") -> str:
    """설명문 간단 수정. 여러 줄 입력 가능, 빈 줄 2번이면 종료."""
    print(f"\n✏️ {label} 수정 (새 내용 입력, 유지하려면 엔터만, 끝내려면 빈 줄 2번)")
    print(f"--- 현재 {label} ---")
    print(text)
    print(f"--- 여기까지 ---")
    print(f"새 {label}를 입력하세요 (그대로 쓰려면 엔터만):")
    lines = []
    empty_count = 0
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "":
            empty_count += 1
            if empty_count >= 2:
                break
            if not lines:
                # 첫 줄부터 엔터 → 유지
                return text
            lines.append("")
            continue
        empty_count = 0
        lines.append(line)
    if not lines or not "".join(lines).strip():
        return text
    return "\n".join(lines).strip()


def edit_script(script: list) -> list:
    """대본 장면별 간단 수정. 장면 번호 → 내용/시각 수정, 엔터 유지."""
    import copy
    script = copy.deepcopy(script)
    print("\n✏️ 대본 수정 (장면 번호 입력 → 내용/시각 수정, 엔터 유지, 0 종료)")
    while True:
        for s in script:
            print(f"   [{s.get('scene')}] {s.get('time','')} | 내용: {s.get('content','')[:40]} | 시각: {s.get('visual','')[:40]}")
        sel = input("\n수정할 장면 번호 (0=종료): ").strip()
        if sel == "0" or sel == "":
            break
        try:
            idx = int(sel) - 1
            if 0 <= idx < len(script):
                cur = script[idx]
                print(f"   현재 내용: {cur.get('content','')}")
                new_c = input("   새 내용 (엔터=유지): ").strip()
                if new_c:
                    cur["content"] = new_c
                print(f"   현재 시각: {cur.get('visual','')}")
                new_v = input("   새 시각 (엔터=유지): ").strip()
                if new_v:
                    cur["visual"] = new_v
                print("   ✅ 수정됨")
        except ValueError:
            print("   숫자를 입력하세요.")
    return script


def has_hanja(text: str) -> bool:
    """한자(중국어 문자) 포함 여부 — 대사 품질 체크용
    (AI가 가끔 한자를 섞어 출력 → TTS 발음 오류 + 말풍선/자막 오염 원인)"""
    return any('\u4e00' <= ch <= '\u9fff' or '\u3400' <= ch <= '\u4dbf'
               for ch in (text or ""))


def edit_scene_direct(script: list) -> list:
    """장면 대사/시각을 직접 타이핑해서 수정 (메뉴 7번).
    - AI가 한자를 섞거나 단어를 바꾸고 싶을 때, 해당 장면만 골라 손으로 고침
    - 장면 목록에 한자 포함 장면 ⚠ 표시 / 엔터=유지 / 0=종료 / 수정 후 즉시 결과 표시"""
    import copy
    script = copy.deepcopy(script)

    def _ask(prompt: str) -> str:
        try:
            return input(prompt).strip()
        except EOFError:
            return ""

    print("\n✏️ 대본 직접 수정 (장면 번호 → 새 문구 타이핑, 엔터=유지, 0=종료)")
    while True:
        print("\n   ── 현재 대본 (⚠ = 한자 포함 장면) ──")
        for s in script:
            mark = " ⚠️" if has_hanja(s.get('content', '')) else ""
            print(f"   [{s.get('scene')}] 내용: {s.get('content', '')}{mark}")
        sel = _ask("\n수정할 장면 번호 (엔터/0=종료): ")
        if sel in ("", "0"):
            break
        try:
            idx = int(sel) - 1
        except ValueError:
            print("   ⚠ 숫자를 입력하세요 (예: 3)")
            continue
        if not (0 <= idx < len(script)):
            print(f"   ⚠ 1~{len(script)} 범위로 입력하세요")
            continue
        cur = script[idx]
        print(f"\n   [장면 {cur.get('scene')}]")
        print(f"   현재 내용: {cur.get('content', '')}")
        new_c = _ask("   새 내용 입력 (엔터=유지): ")
        if new_c:
            cur["content"] = new_c
        print(f"   현재 시각: {cur.get('visual', '')}")
        new_v = _ask("   새 시각 입력 (엔터=유지): ")
        if new_v:
            cur["visual"] = new_v
        if new_c or new_v:
            print("   ✅ 수정 완료!")
            print(f"   [장면 {cur.get('scene')}] 내용: {cur.get('content', '')}")
            print(f"              시각: {cur.get('visual', '')}")
        else:
            print("   (변경 없음)")
    return script


def select_text_api():
    """텍스트 생성 API 선택 (Groq는 실시간 모델 목록 조회 후 선택)"""
    print("\n🔌 텍스트 생성 API를 선택하세요:")
    print("   1. Gemini (기본)")
    print("   2. OpenRouter")
    print("   3. Groq (모델 목록에서 선택)")
    api_sel = input("\n선택 (1/2/3, 엔터=Gemini): ").strip()
    api_map = {"1": "gemini", "2": "openrouter", "3": "groq"}
    api_choice = api_map.get(api_sel, "gemini")

    groq_model = None
    if api_choice == "groq":
        print("\n📋 Groq 모델 목록 조회 중...")
        models = TextGenerator.list_groq_models()
        if models:
            for idx, m in enumerate(models, 1):
                print(f"   {idx}. {m}")
            print("   💡 429(할당량) 오류가 뜨면 다른 번호로 다시 선택해보세요")
            sel = input(f"\nGroq 모델 선택 (1-{len(models)}, 엔터=1): ").strip()
            if sel.isdigit() and 1 <= int(sel) <= len(models):
                groq_model = models[int(sel) - 1]
            else:
                groq_model = models[0]
            print(f"→ 선택한 모델: {groq_model}")
        else:
            print("⚠️ 모델 목록 조회 실패 → Groq 기본 모델로 진행")
    return api_choice, groq_model


def create_text_gen(api_choice, groq_model=None):
    """TextGenerator 생성 (초기화 실패 시 Gemini로 폴백)"""
    try:
        return TextGenerator(api_type=api_choice, groq_model=groq_model), api_choice
    except Exception as e:
        print(f"⚠️ {api_choice} 초기화 실패: {e}")
        print("→ Gemini로 재시도합니다.")
        return TextGenerator(api_type="gemini"), "gemini"


def _ask_playback_speed() -> float:
    """영상 재생 배속을 사용자에게 입력받음 (엔터 = config 기본값). 허용 범위 0.5~3.0"""
    import re
    default = float(VIDEO_PLAYBACK_SPEED or 1.0)
    raw = input(f"\n⚡ 재생 배속 (1.0=원본 | 예: 1.1, 1.2, 1.5 | 엔터=기본값 {default}): ").strip()
    if not raw:
        print(f"   → 기본값 {default}배속 사용")
        return default
    # "1.2", "1.2배속", "x1.5", "1.5x" 등 숫자 부분만 추출
    m = re.search(r"\d+(?:\.\d+)?", raw.lower())
    if not m:
        print(f"   ⚠️ 숫자로 해석 불가 → 기본값 {default}배속 사용")
        return default
    v = float(m.group())
    if 0.5 <= v <= 3.0:
        print(f"   → {v}배속 적용")
        return v
    print(f"   ⚠️ 지원 범위는 0.5~3.0배속 → 기본값 {default}배속 사용")
    return default


def _overlay_targets_with_content_change(plan: dict) -> list:
    """텍스트만 다시 그릴 장면 = 대사만 바뀐 장면 + (이미지 재생성을 건너뛴) 대사 바뀐 장면"""
    rows = {r["scene"]: r for r in (plan.get("rows") or [])}
    out = list(plan.get("image_overlay") or [])
    for i in (plan.get("skipped_image_regen") or []):
        r = rows.get(i)
        if r and r.get("content_changed"):
            out.append(i)
    return sorted(set(out))


def _script_only_flow(script, titles, description, idea, text_result) -> bool:
    """script.txt 수정분만 반영해서 이미지/텍스트/음성/영상을 다시 만든다.

    - 대사만 바뀐 장면: API/SD 재호출 없이 텍스트만 다시 그림 (base 원본 사용)
    - 시각이 바뀐 장면: 로컬 SD(무료)로 이미지 재생성 → 대사도 함께 그림
    - 음성: edge-tts(무료)로 변경된 장면만 재생성
    - 영상: FFmpeg로 다시 생성  → 이후 공통 업로드 단계로 진행
    반환: True(계속) / False(중단)
    """
    plan = script_store.plan_tasks(script, overlay_key=overlay_mod.current_key)
    print("\n📋 script.txt 기준 작업 계획")
    print(plan["summary"])
    if not plan["image_regen"] and not plan["image_overlay"] and not plan["audio_regen"]:
        print("ℹ️ 바뀐 장면이 없습니다. 영상만 다시 만들 수 있습니다.")

    skipped_regen = []
    # 1) 시각이 바뀐 장면 → 이미지 다시 생성 (로컬 SD = API 호출 없음)
    if plan["image_regen"]:
        print(f"\n🖼 이미지 재생성 대상: {', '.join(map(str, plan['image_regen']))}")
        print("   1. 로컬 SD 3.5 Large Turbo (Q4 GGUF · API 호출 없음)")
        print("   2. 로컬 SDXL-Turbo (API 호출 없음)")
        print("   3. Gemini 이미지 API (인터넷 필요)")
        print("   4. 건너뛰기 (기존 이미지 유지 + 대사만 다시 그리기)")
        sel = (input("   선택 (엔터=1): ").strip() or "1")
        mode_key = {"1": "sd_gguf", "2": "sd_sdxl", "3": "gemini", "4": "skip"}.get(sel, "sd_gguf")
        if mode_key == "skip":
            skipped_regen = list(plan["image_regen"])
        else:
            res = pipeline.generate_images(script, plan["image_regen"], mode_key)
            done = res.get("done") or []
            skipped_regen = [i for i in plan["image_regen"] if i not in done]
    plan["skipped_image_regen"] = skipped_regen

    # 2) 텍스트(대사) 다시 그리기 — API 호출 없음
    targets = _overlay_targets_with_content_change(plan)
    if targets:
        print(f"\n💬 텍스트 다시 그리기 대상: {', '.join(map(str, targets))} (이미지 재생성 없음)")
        pipeline.render_overlays(script, targets)

    # 3) 음성 (edge-tts 무료)
    audio_idx = []
    if plan["audio_regen"]:
        print(f"\n🎤 음성 재생성 대상: {', '.join(map(str, plan['audio_regen']))} (edge-tts 무료)")
        print("   1. 변경된 장면만 (엔터)   2. 전체 장면   3. 건너뛰기")
        sel = (input("   선택 (엔터=1): ").strip() or "1")
        if sel == "1":
            audio_idx = list(plan["audio_regen"])
        elif sel == "2":
            audio_idx = list(range(1, len(script) + 1))
    if audio_idx:
        pipeline.generate_audio(script, audio_idx)
    else:
        print("\n🎤 음성: 새로 만들지 않습니다.")

    merged = Path(OUTPUT_DIR) / "audio" / "full_narration.mp3"
    if audio_idx or not merged.exists():
        pipeline.merge_audio(script)

    # 4) 영상
    sel = (input("\n🎬 영상을 다시 만들까요? (1=네(엔터) / 2=아니요): ").strip() or "1")
    if sel == "2":
        return False
    speed = _ask_playback_speed()
    res = pipeline.build_video(script, titles=titles, speed=speed)
    if not res.get("ok"):
        print(f"❌ 영상 생성 실패: {res.get('reason')}")
        return False

    # 5) 업로드 단계에서 사용할 수 있도록 체크포인트 갱신 (단계 4 = 영상까지 완료)
    image_paths = [str(script_store.scene_image_path(i)) for i in range(1, len(script) + 1)
                   if script_store.scene_image_path(i).exists()]
    audio_paths = [str(script_store.scene_audio_path(i)) for i in range(1, len(script) + 1)
                   if script_store.scene_audio_path(i).exists()]
    save_checkpoint(4, {
        "idea": idea,
        "text_result": text_result,
        "image_paths": image_paths,
        "img_choice": "script_only",
        "audio_paths": audio_paths,
        "full_audio": str(merged) if merged.exists() else None,
        "video_path": res.get("path"),
    })
    return True


def _launch_web_editor():
    """웹 편집기(webapp.py)를 새 콘솔 창에서 실행하고 브라우저를 연다"""
    import subprocess
    import time
    webapp = Path(__file__).resolve().parent / "webapp.py"
    if not webapp.exists():
        print(f"❌ webapp.py 를 찾을 수 없습니다: {webapp}")
        return
    url = "http://127.0.0.1:8765/"
    print(f"\n🌐 웹 편집기를 실행합니다 → {url}")
    print("   (새로 열린 콘솔 창을 닫으면 웹 편집기도 종료됩니다)")
    try:
        kwargs = {}
        if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_CONSOLE"):
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
        subprocess.Popen([sys.executable, "-X", "utf8", str(webapp), "--open"],
                         cwd=str(webapp.parent), **kwargs)
    except Exception as e:
        print(f"⚠️ 실행 실패: {e}")
        print("   직접 실행: .\\venv\\Scripts\\python.exe -X utf8 webapp.py --open")
        return
    try:
        import webbrowser
        time.sleep(2)
        webbrowser.open(url)
    except Exception:
        pass


def main_flow():
    """메인 실행 함수 (실제 흐름)"""
    print_banner()
    
    # ---- 시작 방식 선택 (체크포인트 + 저장 파일 기반) ----
    checkpoint = load_checkpoint()
    start_step = 1
    text_result = None
    titles = []
    description = ""
    script = []
    idea = ""

    # ---- script.txt 수정분을 체크포인트에 반영 (손으로 고친 대본을 우선) ----
    if checkpoint:
        sync = script_store.sync_script_to_checkpoint(create=False, apply=True)
        if sync.get("changed"):
            print("\n📝 script.txt 수정을 감지했습니다 → 체크포인트에 반영했습니다.")
            print(f"   {sync.get('summary')}")
            checkpoint = load_checkpoint()

    saved_files = [f for f in ("titles.txt", "title.txt", "description.txt", "script.txt")
                   if (Path(OUTPUT_DIR) / f).exists()]

    choice = "1"
    if checkpoint or saved_files:
        print("\n🚩 시작 방식을 선택하세요:")
        print("   1. 처음부터 새로 시작")
        if checkpoint:
            print(f"   2. 이어서 진행 (체크포인트: 단계 {checkpoint['step']}까지 저장됨)")
            print("   3. 특정 단계부터 시작 (체크포인트 데이터 사용)")
        if saved_files:
            print("   4. 저장된 제목/설명/대본 파일에서 불러오기 (시작 단계 선택)")
        if (Path(OUTPUT_DIR) / "script.txt").exists():
            print("   5. script.txt 수정분만 반영해서 제작 (텍스트 생성 API 호출 없음) ★")
            print("   6. 웹 편집기 열기 (브라우저에서 대본·이미지·텍스트 편집)")
        choice = input("\n선택 (엔터=1): ").strip() or "1"

        if choice == "2" and checkpoint:
            start_step = checkpoint['step'] + 1
            text_result = checkpoint['data'].get('text_result')
            if text_result:
                titles = text_result.get('titles', [])
                description = text_result.get('description', '')
                script = text_result.get('script', [])
            print(f"➡️  단계 {start_step}부터 이어서 진행합니다.")
        elif choice == "3" and checkpoint:
            print("\n단계 선택:")
            print("   1. 텍스트 생성")
            print("   2. 이미지 생성")
            print("   3. 음성 생성")
            print("   4. 영상 편집")
            print("   5. 유튜브 업로드")
            step_choice = input("\n시작할 단계 (1-5): ").strip()
            start_step = int(step_choice) if step_choice.isdigit() and 1 <= int(step_choice) <= 5 else 1
            if start_step > 1 and checkpoint['data'].get('text_result'):
                text_result = checkpoint['data']['text_result']
                titles = text_result.get('titles', [])
                description = text_result.get('description', '')
                script = text_result.get('script', [])
            print(f"➡️  단계 {start_step}부터 시작합니다.")
        elif choice == "4":
            titles, description, script = restore_saved_files()
            # 파일에 없는 부분은 체크포인트로 보완
            if checkpoint and (not script or not titles):
                tr = checkpoint['data'].get('text_result') or {}
                titles = titles or tr.get('titles', [])
                description = description or tr.get('description', '')
                script = script or tr.get('script', [])
            if not script:
                print("❌ 복구 가능한 대본이 없습니다 (script.txt/체크포인트 없음).")
                print("   처음부터 새로 시작해주세요.")
                return
            text_result = {"titles": titles, "description": description, "script": script}
            print(f"\n✅ 복구 완료: 제목 {len(titles)}개 / 설명 {len(description)}자 / 대본 {len(script)}장면")
            if titles:
                print(f"   대표 제목: {titles[0]}")
            print("\n어디서부터 이어서 할까요?")
            print("   2. 이미지 생성")
            print("   3. 음성 생성")
            print("   4. 영상 편집")
            print("   5. 유튜브 업로드")
            step_choice = input("\n시작할 단계 (2-5, 엔터=2): ").strip()
            start_step = int(step_choice) if step_choice.isdigit() and 2 <= int(step_choice) <= 5 else 2
            print(f"➡️  단계 {start_step}부터 시작합니다.")
        elif choice == "5":
            # ---- script.txt 만 고쳐서 다시 제작 (텍스트 생성 API 호출 없음) ----
            sync = script_store.sync_script_to_checkpoint(create=True, apply=True)
            script = sync.get("script") or []
            if not script:
                print("❌ script.txt 가 없거나 비어 있습니다.")
                return
            titles, description = script_store.load_text_files()
            idea = ((checkpoint or {}).get('data') or {}).get('idea') or "(script.txt 수정 모드)"
            text_result = {"titles": titles, "description": description, "script": script}
            checkpoint = load_checkpoint()
            print(f"\n📌 script.txt 기준: 제목 {len(titles)}개 / 대본 {len(script)}장면")
            if sync.get("changed"):
                print(f"   변경 요약: {sync.get('summary')}")
            if not _script_only_flow(script, titles, description, idea, text_result):
                print("\n⏹️ 제작을 중단했습니다.")
                return
            start_step = 5   # 아래 공통 업로드 단계로 이동
        elif choice == "6":
            _launch_web_editor()
            return
        else:
            choice = "1"

    if choice == "1":
        clear_checkpoint()

    if start_step >= 2:
        idea = checkpoint['data'].get('idea', '') if checkpoint else ''
        if not idea:
            idea = "(이전 작업 이어하기)"
    else:
        print("💡 유튜브 영상 아이디어를 입력해주세요!")
        print("   (예: 파이썬 자동화, 요리 레시피, 여행 브이로그 등)")
        print()
        idea = input("🎯 아이디어: ").strip()
        if not idea:
            print("❌ 아이디어를 입력해주세요!")
            return

    print(f"\n🚀 영상 제작을 시작합니다: '{idea}'")
    
    # 단계 1: 텍스트 생성 (2단계: 제목/설명 -> 대본)
    if start_step <= 1:
        print_step(1, 5, "텍스트 생성 중...")
        text_result = None
        titles = []
        description = ""
        script = []

        # ---- API 선택 (최초 1회, Groq는 모델 목록에서 선택) ----
        api_choice, groq_model = select_text_api()
        text_gen, api_choice = create_text_gen(api_choice, groq_model)

        # ---- 1단계: 제목 + 설명문 ----
        approved = False
        while not approved:
            if not titles:
                print(f"📝 제목/설명 생성 중... (API: {api_choice})")
                titles = text_gen.generate_title(idea)
                description = text_gen.generate_description(idea)
                save_text_files(titles, description)
            print("\n" + "="*60)
            print("  ✅ 제목/설명 생성 완료! (대본은 다음 단계)")
            print("="*60)
            print("\n📌 생성된 제목:")
            for idx, title in enumerate(titles, 1):
                print(f"   {idx}. {title}")
            print(f"\n📌 생성된 설명:\n{description}")
            print("\n제목/설명 확인 (대본은 다음 단계)")
            print("   1. 승인 (대본 단계로)")
            print("   2. 문구 수정 (제목/설명)")
            print("   3. 다시 생성")
            print("   4. API 변경해서 다시 생성")
            approve = input("\n선택 (1/2/3/4): ").strip()
            if approve == "1":
                approved = True
            elif approve == "2":
                titles = edit_text_list(titles, "제목")
                description = edit_text_block(description, "설명문")
                save_text_files(titles, description)
            elif approve == "3":
                titles = []
            elif approve == "4":
                print("\n🔄 API 변경:")
                api_choice, groq_model = select_text_api()
                text_gen, api_choice = create_text_gen(api_choice, groq_model)
                titles = []
            else:
                print("   ⚠ 1~4 중에서 선택하세요 (현재 제목/설명 유지)")

        # ---- 주인공 캐릭터 (대본·이미지 공통 적용) ----
        char_in = input(f"🎭 주인공 캐릭터 (엔터={MAIN_CHARACTER} 고정 / 변경하려면 입력): ").strip()
        character = char_in if char_in else MAIN_CHARACTER
        print(f"   → 주인공 '{character}' 캐릭터로 대본·이미지 생성\n")

        # ---- 2단계: 대본 (확정 제목 전달) ----
        approved = False
        while not approved:
            if not script:
                print(f"📝 대본 생성 중... (API: {api_choice}, 제목반영, 주인공={character})")
                script = text_gen.generate_script(idea, title_context=titles[0] if titles else None, character=character)
                text_result = {"titles": titles, "description": description, "script": script}
                save_text_files(titles, description)
            print("\n" + "="*60)
            print("  ✅ 대본 생성 완료!")
            print("="*60)
            print("\n📌 확정 제목:", titles[0] if titles else "")
            print("\n📌 생성된 대본:")
            for scene in script:
                hanja_mark = "  ⚠️ 한자 포함" if has_hanja(scene.get('content', '')) else ""
                print(f"\n   [장면 {scene.get('scene')}] ({scene.get('time', '')}){hanja_mark}")
                print(f"   내용: {scene.get('content', '')}")
                print(f"   시각: {scene.get('visual', '')}")
            print("\n대본 확인 -- 이 결과로 진행하시겠습니까?")
            print("   1. 승인 (진행)")
            print("   2. 문구 수정 (대본)")
            print("   3. 다시 생성")
            print("   4. API 변경해서 다시 생성")
            print("   5. 빈 문구 채우기 (빈 내용/시각 자동 채움)")
            print("   6. 장면 수정 (해당 장면만 새로 작성)")
            print("   7. 직접 수정 (장면 대사/시각 직접 타이핑 — 한자 등 AI 오류 수정)")
            approve = input("\n선택 (1/2/3/4/5/6/7): ").strip()
            if approve == "1":
                approved = True
            elif approve == "2":
                script = edit_script(script)
                save_script_file(script)
                text_result = {"titles": titles, "description": description, "script": script}
            elif approve == "5":
                script = text_gen.fill_empty_scenes(idea, script, title_context=titles[0] if titles else None, character=character)
                save_text_files(titles, description)
                save_script_file(script)
                text_result = {"titles": titles, "description": description, "script": script}
            elif approve == "6":
                sel = input(f"\n다시 작성할 장면 번호 (1-{len(script)}): ").strip()
                try:
                    script = text_gen.regenerate_scene(idea, script, int(sel), title_context=titles[0] if titles else None, character=character)
                    save_text_files(titles, description)
                    save_script_file(script)
                    text_result = {"titles": titles, "description": description, "script": script}
                except ValueError:
                    print("   숫자를 입력하세요.")
            elif approve == "7":
                script = edit_scene_direct(script)
                save_script_file(script)
                text_result = {"titles": titles, "description": description, "script": script}
            elif approve == "3":
                script = []
            elif approve == "4":
                print("\n🔄 API 변경:")
                api_choice, groq_model = select_text_api()
                text_gen, api_choice = create_text_gen(api_choice, groq_model)
                script = []
            else:
                print("   ⚠ 1~7 중에서 선택하세요 (현재 대본 유지)")
        text_result = {"titles": titles, "description": description, "script": script}

        save_script_file(script)
        clean_stale_scenes(len(script))
        save_checkpoint(1, {
            "idea": idea,
            "text_result": text_result,
            "character": character
        })
    else:
        # 단계 1 생략: 저장된 텍스트 사용 (이어하기 / 파일 복구)
        if text_result is None and checkpoint:
            text_result = checkpoint['data'].get('text_result')
        if text_result:
            titles = text_result.get('titles', [])
            description = text_result.get('description', '')
            script = text_result.get('script', [])
        if not script:
            f_titles, f_desc, f_script = restore_saved_files()
            titles = titles or f_titles
            description = description or f_desc
            script = script or f_script
            if f_script:
                text_result = {"titles": titles, "description": description, "script": script}
        if not script:
            print("❌ 대본이 없어 진행할 수 없습니다. 처음부터(단계 1) 시작하세요.")
            return
        character = ((checkpoint or {}).get('data') or {}).get('character') or MAIN_CHARACTER
        print(f"📌 저장된 텍스트 사용: 제목 {len(titles)}개 / 대본 {len(script)}장면 (주인공={character})")
        clean_stale_scenes(len(script))
    
    # 단계 2: 이미지 생성
    if start_step <= 2:
        print_step(2, 5, "이미지 생성 중...")

        image_paths = []
        resumed = False
        start_idx = 1
        partial = checkpoint['data'].get('img_partial') if checkpoint else None
        if partial and partial.get('paths') is not None:
            print(f"\n💾 중단된 이미지 작업 발견: {len(partial['paths'])}/{len(script)} 장 완성")
            r = input("   이어서 생성할까요? (y=이어서 / n=처음부터): ").strip().lower()
            if r == 'y':
                image_paths = list(partial['paths'])
                img_choice = partial.get('img_choice', '1')
                if img_choice == '1':
                    img_gen = ImageGenerator(mode="sd_local", local_model_path=SD_LOCAL_CHECKPOINT)
                elif img_choice == '2':
                    img_gen = ImageGenerator(mode="sd_local", local_model_path=SD_GGUF_CHECKPOINT)
                else:
                    img_gen = ImageGenerator(mode="placeholder")
                start_idx = partial.get('index', len(image_paths) + 1)
                resumed = True

        if not resumed:
            print("\n🎨 이미지 생성 방식을 선택하세요:")
            print("   1. 로컬 SDXL-Turbo (폴더, 1080Ti 검증 43초/장)")
            print("   2. 로컬 SD 3.5 Large Turbo (Q4 GGUF, 1080Ti 검증 ~31초/장·모자이크 해결)")
            print("   3. 플레이스홀더 (테스트용)")
            img_choice = input("\n선택 (1/2/3): ").strip()
            if img_choice == "1":
                ckpt_input = input("SDXL-Turbo 경로 (엔터=기본값): ").strip()
                ckpt_path = ckpt_input if ckpt_input else SD_LOCAL_CHECKPOINT
                img_gen = ImageGenerator(mode="sd_local", local_model_path=ckpt_path)
            elif img_choice == "2":
                img_gen = ImageGenerator(mode="sd_local", local_model_path=SD_GGUF_CHECKPOINT)
            else:
                img_gen = ImageGenerator(mode="placeholder")
            if img_choice == "3":
                image_paths = img_gen.create_placeholder_images(script)
                start_idx = len(script) + 1  # 루프 건너뜀

        if start_idx <= len(script):
            # 장면별 생성 — 오류 발생 시 계속할지 물어봄
            idx = start_idx
            while idx <= len(script):
                scene = script[idx - 1]
                try:
                    out = img_gen.generate_scene_images([scene], start_index=idx)
                    path = out[0] if out else None
                    if path:
                        image_paths.append(path)
                        print(f"   ✅ 완료 [{idx}/{len(script)}]: {path}")
                        idx += 1
                    else:
                        raise Exception("이미지 생성 실패 (None 반환)")
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    print(f"\n   ❌ 장면 {idx} 오류: {e}")
                    act = input("   1. 재시도  2. 건너뛰기  3. 중지 후 저장/종료 : ").strip()
                    if act == "2":
                        idx += 1
                    elif act == "3":
                        save_checkpoint(1, {
                            "idea": idea,
                            "text_result": text_result,
                            "img_partial": {"paths": image_paths, "index": idx, "img_choice": img_choice}
                        })
                        print(f"\n⏸️ 중단: 다음 실행시 '이어서 진행'을 선택하면 장면 {idx}부터 이어서 생성됩니다.")
                        return
                    # 1 또는 그 외 입력 → 재시도 (idx 유지)

        if not image_paths:
            print("⚠️ 이미지 생성 실패. 플레이스홀더로 대체합니다.")
            image_paths = img_gen.create_placeholder_images(script)
        
        print(f"\n✅ 이미지 {len(image_paths)}개 생성 완료")
        script_store.mark_assets(script, kinds=("img",))   # 변경 감지 기준 갱신
        save_checkpoint(2, {
            "idea": idea,
            "text_result": text_result,
            "image_paths": image_paths,
            "img_choice": img_choice
        })
    else:
        image_paths = checkpoint['data'].get('image_paths', []) if checkpoint else []
        img_choice = checkpoint['data'].get('img_choice', '3') if checkpoint else '3'
        if not image_paths:
            imgs_dir = Path(OUTPUT_DIR) / "images"
            found = sorted(imgs_dir.glob("scene_*.png")) if imgs_dir.exists() else []
            if found:
                image_paths = [str(p) for p in found]
                print(f"\n📂 output/images에서 장면 이미지 {len(image_paths)}개 발견 (이전 실행분)")
                for p in image_paths[:3]:
                    print(f"   - {p} ({os.path.getsize(p) // 1024}KB)")
                use = input("   이 이미지들을 사용할까요? (y/n, 엔터=y): ").strip().lower()
                if use == "n":
                    image_paths = []
                    print("   → 이미지를 새로 만들려면 단계 2부터 시작하세요.")
    
    # 단계 3: 음성 생성
    if start_step <= 3:
        print_step(3, 5, "음성(TTS) 생성 중...")
        
        tts_engine = TTSEngine()
        audio_paths = tts_engine.generate_scene_audio(script)
        
        if audio_paths:
            full_audio = tts_engine.merge_audio_files(audio_paths)
            print(f"\n✅ 음성 생성 완료: {len(audio_paths)}개 파일")
        else:
            full_audio = None
            print("⚠️ 음성 생성 실패")
        
        script_store.mark_assets(script, kinds=("audio",))   # 변경 감지 기준 갱신
        save_checkpoint(3, {
            "idea": idea,
            "text_result": text_result,
            "image_paths": image_paths,
            "img_choice": img_choice,
            "audio_paths": audio_paths,
            "full_audio": full_audio
        })
    else:
        audio_paths = checkpoint['data'].get('audio_paths', []) if checkpoint else []
        full_audio = checkpoint['data'].get('full_audio') if checkpoint else None
        if full_audio and not os.path.exists(full_audio):
            print(f"⚠️ 저장된 음성 파일이 없음: {full_audio}")
            full_audio = None
        if not full_audio:
            merged = Path(OUTPUT_DIR) / "audio" / "full_narration.mp3"
            if merged.exists() and merged.stat().st_size > 0:
                full_audio = str(merged)
                audio_paths = sorted(str(p) for p in merged.parent.glob("scene_*.mp3"))
                print(f"📂 병합 음성 재활용: {full_audio}")
    
    # 단계 4: 영상 편집
    if start_step <= 4:
        print_step(4, 5, "영상 편집 중...")
        
        editor = VideoEditor()
        
        # 이미지: 대본 길이와 1:1 보장 (누락 장면은 임시 플레이스홀더로 대체)
        # → 기존 exists 필터는 장면 수가 짧아져 '영상에서 이미지가 빠지고'
        #   장면-음성-자막 인덱스가 엇갈리는 문제가 있었음
        valid_images, missing_images = ensure_scene_images(script, log=print)
        
        # 파일명을 영상 제목으로 설정
        video_filename = f"{titles[0][:30]}.mp4" if titles else "final_video.mp4"
        # 파일명에 사용할 수 없는 문자 제거
        import re
        video_filename = re.sub(r'[\\/*?:"<>|]', "", video_filename)
        
        # 장면별 음성 파일 재구성 (체크포인트 복원 시 목록이 비어있을 수 있음)
        if not audio_paths:
            ap_dir = Path(OUTPUT_DIR) / "audio"
            audio_paths = sorted(str(p) for p in ap_dir.glob("scene_*.mp3")) if ap_dir.exists() else []
        
        # 장면별 표시 시간 = 장면 음성 실제 길이 (동기화)
        scene_durations = editor.measure_scene_durations(audio_paths, len(valid_images), full_audio)
        
        # 자막용 장면 대사 (대본 '내용' — 유효 이미지 수에 맞춤)
        scene_texts = [(s.get("content") or s.get("visual") or "") for s in script[:len(valid_images)]]
        
        # 재생 배속 (매번 입력, 엔터=config 기본값)
        playback_speed = _ask_playback_speed()
        
        video_path = editor.create_video_from_images(valid_images, full_audio, output_file=video_filename,
                                                     scene_durations=scene_durations,
                                                     scene_texts=scene_texts,
                                                     playback_speed=playback_speed)
        
        if not video_path:
            print("⚠️ FFmpeg 실패. MoviePy로 재시도...")
            video_path = editor.create_video_with_moviepy(valid_images, full_audio, output_file=video_filename,
                                                          scene_durations=scene_durations,
                                                          scene_texts=scene_texts,
                                                          playback_speed=playback_speed)
        
        if not video_path:
            print("❌ 영상 생성 실패")
            return
        
        script_store.mark_video_built(script, video_path)   # 변경 감지 기준 갱신
        save_checkpoint(4, {
            "idea": idea,
            "text_result": text_result,
            "image_paths": image_paths,
            "img_choice": img_choice,
            "audio_paths": audio_paths,
            "full_audio": full_audio,
            "video_path": video_path
        })
    else:
        video_path = checkpoint['data'].get('video_path') if checkpoint else None
        if not video_path or not os.path.exists(video_path):
            vids_dir = Path(OUTPUT_DIR) / "videos"
            vids = sorted(vids_dir.glob("*.mp4"), key=os.path.getmtime) if vids_dir.exists() else []
            video_path = str(vids[-1]) if vids else None
            if video_path:
                print(f"📂 기존 영상 재활용: {video_path}")
        if not video_path:
            print("❌ 업로드할 영상이 없습니다. 단계 4(영상 편집)부터 시작하세요.")
            return
    
    # 단계 5: 유튜브 업로드
    print_step(5, 5, "유튜브 업로드 준비...")
    
    print("\n📤 유튜브에 업로드하시겠습니까?")
    print("   1. 지금 업로드 (공개)")
    print("   2. 지금 업로드 (비공개)")
    print("   3. 나중에 업로드 (영상 파일만 저장)")
    
    upload_choice = input("\n선택 (1/2/3): ").strip()
    
    if upload_choice in ["1", "2"]:
        uploader = YouTubeUploader()
        
        print("\n📌 선택할 제목:")
        for i, title in enumerate(titles, 1):
            print(f"   {i}. {title}")
        
        title_choice = input(f"\n제목 선택 (1-{len(titles)}): ").strip()
        try:
            selected_title = titles[int(title_choice) - 1]
        except:
            selected_title = titles[0]
        
        # 공개 설정
        privacy = "public" if upload_choice == "1" else "private"
        
        # 업로드 전 확인
        print(f"\n⚠️  업로드 정보 확인:")
        print(f"   제목: {selected_title}")
        print(f"   공개설정: {'공개' if privacy == 'public' else '비공개'} ({privacy})")
        print(f"   영상파일: {video_path}")
        
        confirm = input("\n업로드 진행하시겠습니까? (y/n): ").strip().lower()
        if confirm != 'y':
            print("업로드가 취소되었습니다.")
            print(f"\n✅ 영상 저장 완료: {video_path}")
            return
        
        result = uploader.upload_video(
            video_path=video_path,
            title=selected_title,
            description=description,
            privacy=privacy
        )
        
        if result["success"]:
            print(f"\n🎉 영상 업로드 완료!")
            print(f"   URL: {result['url']}")
        else:
            print(f"\n❌ 업로드 실패: {result.get('error')}")
    else:
        print(f"\n✅ 영상 저장 완료: {video_path}")
    
    # 완료 - 체크포인트 삭제
    clear_checkpoint()
    
    # 완료
    print(f"""
{'='*60}
  🎬 영상 제작이 완료되었습니다!
{'='*60}
  📁 저장 위치: {os.path.abspath(OUTPUT_DIR)}
  🎬 영상 파일: {video_path}
{'='*60}
    """)


def _stop_info():
    """중단 시 체크포인트 상태 안내"""
    ck = load_checkpoint()
    if ck:
        print(f"💾 체크포인트 유지됨 (완료 단계: {ck['step']}).")
        print(f"   다음 실행시 '이어서 진행'을 선택하면 단계 {ck['step'] + 1}부터 이어집니다.")
        print("   처음부터 다시 하려면 '처음부터 다시 시작'을 선택하세요.")
    else:
        print("ℹ️ 저장된 체크포인트가 없습니다. 다음 실행은 처음부터 시작됩니다.")


def main():
    """오류 발생 시 계속할지 중지할지 묻는 래퍼"""
    while True:
        try:
            main_flow()
            return
        except KeyboardInterrupt:
            print("\n\n⚠️ 사용자에 의해 중단되었습니다.")
            _stop_info()
            return
        except Exception as e:
            print(f"\n❌ 오류 발생: {e}")
            import traceback
            traceback.print_exc()
            print("\n❓ 어떻게 할까요?")
            print("   1. 재시도 (이어하기 메뉴부터 다시 표시)")
            print("   2. 중지하고 종료 (체크포인트 유지 → 다음 실행시 이어하기 가능)")
            choice = input("선택 (1/2): ").strip()
            if choice == "1":
                continue
            _stop_info()
            return


if __name__ == "__main__":
    main()
