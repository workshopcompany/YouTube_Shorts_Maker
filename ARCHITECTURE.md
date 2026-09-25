# 🧭 ARCHITECTURE.md — 시스템 지도 & 수정 가이드

> **이 파일 하나가 프로젝트 전체의 지도입니다.**
> 어떤 AI 모델(또는 사람)이든 이 문서만 읽으면 "무엇을 어디서 고쳐야 하는지" 알 수 있게 유지한다.
> - 코드를 고치기 **전**: §3 수정 매트릭스에서 위치 확인
> - 고친 **후**: 이 문서의 해당 항목 갱신 (지도가 낡으면 다음 수정에서 또 사고가 난다)
> - 최종 갱신: 2026-09-25

---

## 0. 30초 요약 — 이 프로그램의 정체

한 줄 정의: **아이디어 → 제목/대본(AI) → 승인 → 이미지+음성 → 영상(FFmpeg) → 유튜브 업로드** 자동화.
원래 CLI(`main.py`)로 시작했고, 중간 수정이 어려워서 나중에 웹 편집기(`webapp.py` + `webui/index.html`)를 얹었다.

### 설계의 핵심 한 가지: "입구 2개, 엔진 1개"

```
 [입구 A] main.py ──────────────── 터미널(CLI) 대화형 5단계
                                         ↘
 [입구 B] webapp.py + webui/index.html ─→ scripts/web_job.py (백그라운드 워커)
                                         ↘
                     modules/pipeline.py  ← ★유일한 실행 엔진 (execute_spec)
                                         ↓
       modules/*  text_gen · image_gen · tts · video_edit · youtube_upload · overlay
                                         ↓
       modules/script_store.py  ← ★유일한 상태 저장소 (script.txt·checkpoint·변경감지)
```

### 철칙 3가지 (어기면 앞뒤가 틀어짐 — 실제로 그랬음)

1. **기능 규칙은 엔진에만 넣는다.** 입구 파일(`main.py`·`webapp.py`·`index.html`)은 "입력 받아 엔진 호출"만 담당.
   같은 기능을 CLI·웹에 각각 따로 만들면 반드시 한쪽이 낡아서 어긋난다.
2. **대본의 진실은 항상 `output/script.txt` 하나(source of truth).**
   `checkpoint.json`·웹 화면·`project_state.json`은 전부 이 파일에서 파생된 사본이다.
3. **"파일이 실제로 존재하는가"가 완료 판정의 기준.**
   파일이 없는데 "완료"로 기록하면 이후 모든 단계가 그 장면을 건너뛴다. (§7 함정 #1)

---

## 1. 데이터 흐름 — 5단계 파이프라인

| 단계 | step 키 | 하는 일 | 출력(파일) | 담당 |
|---|---|---|---|---|
| ① 텍스트 | `text` | 제목5+설명+대본 생성 / 빈 문구 채우기 / 장면 재작성 | `titles.txt` `title.txt` `description.txt` `script.txt` `checkpoint.json` | `modules/text_gen.py` → `pipeline.generate_text_content` |
| ② 이미지 | `images` | 장면별 AI 이미지 생성 → 원본(base) 보관 → 대사 합성 | `images/base/scene_XX.png`(원본) + `images/scene_XX.png`(완성) | `modules/image_gen.py` → `pipeline.generate_images` |
| ③ 음성 | `tts` | 장면 대사 → mp3 + 전체 병합 음성 | `audio/scene_XX.mp3` `audio/full_narration.mp3` | `modules/tts.py` → `pipeline.generate_audio`/`merge_audio` |
| ④ 영상 | `video` | 이미지+음성 길이 동기화 → MP4 | `videos/*.mp4` | `modules/video_edit.py` → `pipeline.build_video` |
| ⑤ 업로드 | `upload` | 유튜브 업로드 | 유튜브 URL | `modules/youtube_upload.py` → `pipeline.upload_video` |
| (보조) | `overlay` | **이미지 재생성 없이** 대사(말풍선/자막)만 다시 그림 (0.1초·API 없음) | `images/scene_XX.png`만 갱신 | `modules/overlay.py` → `pipeline.render_overlays` |

### 이미지 2층 구조 (반드시 기억)

```
images/base/scene_XX.png  = AI가 그린 순수 그림 (대사 없음)   ← "원본". 지우면 안 됨
images/scene_XX.png       = base + 말풍선/자막 + 삽입이미지    ← 영상에 들어가는 최종본
```
- 대사(`content`)만 고치면 → `overlay` 단계가 base에서 다시 그려 최종본만 갱신 (SD/Gemini 재호출 없음)
- 시각 묘사(`visual`)를 고치면 → `images` 단계가 base부터 새로 생성

### 장면 1개의 상태가 흐르는 길

```
script.txt (내용=대사, 시각=묘사)
   ├─ 내용 바뀜 → overlay만 → scene_XX.png 갱신
   ├─ 시각 바뀜 → images 재생성 → base 갱신 → overlay까지
   └─ 둘 다 그대로 → 아무것도 안 함

images/base/scene_XX.png + script.txt(내용) + overlay_config.json(스타일)
   → overlay.apply_scene() → images/scene_XX.png  → (영상) → 유튜브
```

---

## 3. "무엇을 바꾸고 싶을 때 → 어디를 고친다" 매트릭스

> 새 기능을 만들기 전에 이 표를 먼저 볼 것. **여러 곳을 동시에 고쳐야 하는 항목은 ★ 표시.**

| 바꾸고 싶은 것 | 고칠 파일 → 함수 | 함께 봐야 할 것 (★ 파급) |
|---|---|---|
| 이미지 프롬프트 문구/스타일 | `modules/image_gen.py::_build_sd_prompt` | `config.py::IMAGE_STYLE`(Gemini용 문구), `config.py::CHARACTER_PROMPT_EN` |
| 주인공 캐릭터 | `config.py::MAIN_CHARACTER` / `CHARACTER_PROMPT_EN` | ★ `modules/text_gen.py`(대본 생성 시 캐릭터 설명), 웹 ①탭 `gen-char` 입력창 |
| SD 스텝/디바이스/모델 | `config.py::SD_STEPS`·`SD_DEVICE`·`SD_GGUF_CHECKPOINT`·`SD_LOCAL_CHECKPOINT` | `modules/image_gen.py::_load_sd_local`, `modules/pipeline.py::make_image_generator` |
| 이미지 생성 모델 선택지 추가 | `modules/pipeline.py::IMAGE_MODES` + `make_image_generator` | ★ 웹: ②탭 `<select id="scene-image-mode">`, ③탭 `image-mode`(둘 다 옵션 추가해야 보임) |
| 대사(자막/말풍선) 그리는 방식 | `modules/overlay.py::draw_text` | `DEFAULT_CONFIG` 키, ②탭 슬라이더(`cfg-*`), `render_preview`(미리보기 동일해야 함) |
| 새 스타일/프레임 종류 추가 | `modules/overlay.py::style_labels/frame_labels` + `draw_text`/`draw_insert` | ②탭 select 옵션은 `build_state.styles/frames`로 자동 채워짐(수정 불요) |
| 삽입 이미지(박아 넣기) 동작 | `modules/overlay.py::draw_insert` | `DEFAULT_INSERT`, `insert_path`, ②탭 `ins-*` 슬라이더, `webapp.save_overlay` |
| 원본(base) 보관 규칙 | `modules/overlay.py::save_base_from`, `create_placeholder_base`, `is_placeholder` | ★ `modules/image_gen.py`(생성 직후 저장), `webapp.upload_base_image`, `build_state`(is_placeholder) |
| 장면 추가/삭제 시 동작 | `webapp.py::save_script`(`_clean_scenes` + 플레이스홀더 생성) | ★ `script_store.parse_script_text`(빈 장면 보존), `sync_script_to_checkpoint`(길이 초과분 잘라냄) |
| 변경 감지 기준(무엇을 다시 만들지) | `modules/script_store.py::plan_tasks`, `scene_signature`, `mark_assets`, `update_scene_signatures`, `scene_status` | ★ `modules/pipeline.py` 각 단계 끝의 mark 호출, `overlay.current_key`(합성 해시) |
| 재생 배속 / 해상도 / FPS | `config.py::VIDEO_PLAYBACK_SPEED`·`VIDEO_WIDTH/HEIGHT/FPS` | `modules/video_edit.py`, 웹 ③탭 배속 입력, `spec["speed"]` |
| TTS 음성/속도/무음 | `config.py::TTS_VOICE`·`TTS_SPEED`·`SCENE_GAP_MS` | `modules/tts.py`, `pipeline.generate_audio/merge_audio` |
| 새 제작 단계 추가 (예: 썸네일) | `modules/pipeline.py::execute_spec`에 `elif step == "…"` | ★ 웹: ③탭 체크박스 + `startBuild()`의 `spec.steps`, `webapp` 엔드포인트 불요(스펙으로 전달됨) |
| 새 API 추가 | `webapp.py` Handler `do_POST`/`do_GET` 분기 + 액션 함수 | ★ `webui/index.html::api()` 호출부 |
| 웹 UI 버튼/문구 | `webui/index.html` (마크업 + 해당 JS 함수) | 백엔드 규칙은 건드리지 말 것 |
| 업로드 기본 공개범위/제목 | `modules/pipeline.py::upload_video`(privacy 기본), 웹 ④탭 select | `youtube_upload.py::upload_video` |
| 체크포인트/이어하기 동작 | `modules/script_store.py::load/save_checkpoint`, `sync_script_to_checkpoint` | `main.py` 시작메뉴(2·3·4·5번), `webapp.save_checkpoint_state` |

### "이 증상이면 여기를 본다" (역방향 색인)

| 증상 | 1차 의심 위치 |
|---|---|
| 이미지가 안 만들어짐(그대로임) | ① 웹서버가 **venv 파이썬**인가(`/api/state.torch_available`) ② `output/web_job.log` ③ `image_gen._load_sd_local`/`generate_with_sd_local` |
| 이미지가 만들어졌는데 화면이 옛것 | `webapp.get_preview`(캐시), `loadState(true)` 강제 새로고침, 브라우저 캐시 |
| 대사를 고쳤는데 영상이 옛 대사 | `script_store.plan_tasks`의 `image_overlay`(overlay_sig 비교), `pipeline.render_overlays` |
| 시각을 고쳤는데 이미지가 안 바뀜 | `plan_tasks`의 `image_regen`(scene_sig의 visual 비교), `sync_script_to_checkpoint` 반영 여부 |
| 저장했는데 장면이 사라짐 | `script_store.parse_script_text`(빈 장면 보존), `webapp._clean_scenes` |
| 새 장면 이미지가 "장면 N" 그림 | 플레이스홀더 상태 → `overlay.is_placeholder`, 🎨 새 이미지 만들기 필요(정상 동작) |
| 작업이 시작조차 안 됨(로그 없음) | `webapp.start_job` 반환값·`/api/job.running`(이전 작업 잔여), UI의 조용한 return |
| 서버가 두 개 떠 있음 | `webapp.main()` 단일 인스턴스 가드(§7 함정 #7) |
| 삭제 후 원본이 회색/단색 | `overlay.is_suspect_image`, `generate_with_sd_local`(실패 시 파일 보존) |

---

## 4. 상태 파일 & 단일 진실 원천(SoT) 규칙

| 파일 | 무엇의 SoT인가 | 쓰는 주체 (쓰기) | 읽는 주체 (읽기) |
|---|---|---|---|
| `output/script.txt` | **대본(내용·시각)의 유일한 원본** | 웹 ①탭 저장(`webapp.save_script`), CLI(`main.save_script_file`), AI 대본 생성(`pipeline`) | 거의 모든 모듈(`script_store.load_script_file`) |
| `output/script.txt.bak` | 직전 대본 백업 | `save_script_file(backup=True)` | `restore_saved_files`(복구용) |
| `output/checkpoint.json` | 이어하기 진행 상태(step 0~5 + idea/제목/설명/대본) | `script_store.save_checkpoint`, `sync_script_to_checkpoint` | `main.py` 시작메뉴, `webapp.build_state` |
| `output/project_state.json` | **변경 감지 기준선(서명)** | `update_scene_signatures`, `mark_assets`, `mark_overlay_applied(_map)`, `mark_video_built` | `plan_tasks`, `scene_status`, `build_state` |
| `output/overlay_config.json` | 말풍선/자막 + 삽입 스타일 설정 | `overlay.save_config` (부분 병합), `pipeline.execute_spec`(spec.overlay) | `draw_text`, `draw_insert`, `current_key`, `build_state` |
| `output/prompt_cache.json` | 한글 묘사→영어 프롬프트 번역 캐시 | `image_gen._cache_put` | `image_gen.translate_prompt` |
| `output/web_job_spec.json` | 마지막 웹 작업 스펙 | `webapp.start_job` | `scripts/web_job.py` |
| `output/web_job.log` | 웹 작업 실시간 로그 | 워커 stdout 리다이렉트 | `webapp.job_status`(③탭 로그), 사람 |
| `output/images/base/…` | **이미지 원본**(텍스트 없는 AI 그림) | `image_gen`(생성 직후), `webapp.upload_base_image` | `overlay.apply_scene`(재합성 소스) |
| `output/images/base/*.placeholder` | "이 원본은 임시" 표식 | `overlay.create_placeholder_base` | `overlay.is_placeholder`, `build_state` |

**SoT 규칙 4개**
1. **대본은 `script.txt`만 본다.** 체크포인트·웹 상태는 사본이며, 시작/저장 시 `sync_script_to_checkpoint`가 script.txt 기준으로 맞춘다.
2. **완료 판정 = 파일 존재 + 서명 일치.** 서명 기록(`project_state.json`)은 "파일이 실제로 있을 때만" 갱신한다.
3. **상태 파일(`checkpoint.json`·`project_state.json`)은 손으로 편집하지 않는다.** 이상하면 해당 작업을 다시 실행해서 갱신한다.
4. **`images/base/`를 지우면 원본 복구 불가**(재생성만 가능). `overlay_config.json`도 여러 기능이 공유하므로 확인 없이 되돌리지 않는다.
5. **🎨 이미지 재생성 버튼은 `overlay_config.json`에 쓰지 않는다.** 예전에는 `spec.overlay`로 ②탭 슬라이더 값이 저장돼 "설정이 몰래 바뀐" 것처럼 보였다 → 이미지 버튼은 스펙에 `overlay` 키를 넣지 않고, 합성(overlay) 단계는 **저장된 설정을 읽어서** 실행한다. 설정 저장은 ②탭 `💾 설정만 저장` / `🖌 다시 그리기`로만.

---

## 5. 변경 감지 엔진 (서명 시스템) — 가장 사고가 많은 곳

### 서명(signature)이란
```python
scene_signature(scene) = {"content": hash(대사), "visual": hash(시각묘사)}   # script_store.py
overlay.current_key(scene, cfg, idx) = hash(대사 + 설정 + 삽입파일 상태)      # overlay.py
```
`project_state.json`에 **기준선**이 저장된다:

```json
{
  "scene_sig":  [ {content, visual}, … ],   // "지금 대본" 서명 (update_scene_signatures)
  "img_sig":    [ {content, visual}, … ],   // 이미지를 마지막으로 만들었던 시점의 대본 서명
  "audio_sig":  [ {content, visual}, … ],   // 음성을 마지막으로 만들었던 시점
  "video_sig":  [ {content, visual}, … ],   // 영상을 마지막으로 만들었던 시점
  "overlay_sig": { "1": "hash…", … },       // 장면별 텍스트 합성 해시(overlay.current_key)
  "video_path": "output\\videos\\….mp4",
  "scene_count": 13, "updated": "…"
}
```

### `plan_tasks()` 가 내리는 결론 (핵심 로직)
| 비교 | 결론(plan 키) | 실행되는 단계 |
|---|---|---|
| `scene_sig.visual ≠ img_sig.visual` 또는 이미지 파일 없음 | `image_regen` | **images**(재생성) → overlay |
| `scene_sig.content ≠ img_sig.content` | `image_overlay` | **overlay**(텍스트만 다시) |
| `scene_sig.content ≠ overlay_sig[장면]` (설정 변경 포함) | `image_overlay` | **overlay** |
| `scene_sig ≠ audio_sig` 또는 음성 파일 없음 | `audio_regen` | **tts** |
| 위 셋 중 하나라도 있거나 `scene_sig ≠ video_sig`/영상 없음 | `video_stale` | **video** |

### 사고 방지 규칙 (반드시 지킬 것)
1. **모든 `mark_*` 호출은 "파일이 실제로 존재할 때만"** — 실패·플레이스홀더를 완료로 기록하면 영원히 건너뛴다. (`mark_assets`는 이 규칙이 코드에 내장됨)
2. **모든 mark는 "현재 대본 서명"으로 기록** — 옛 서명으로 기록하면 다음 비교에서 항상 "변경됨"으로 오판한다.
3. **새 단계를 추가하면 그 단계의 mark도 같이 추가** — 안 하면 매 제작마다 그 단계가 다시 실행된다.
4. **`overlay.current_key`에 영향을 주는 설정을 추가**하면 `DEFAULT_CONFIG`에 키를 등록해야 감지된다(등록 안 하면 설정을 바꿔도 재합성 안 됨).
5. 임시 이미지(플레이스홀더)는 **표식 파일(`.placeholder`)** 로 구분 — 실제 생성/업로드 시 `save_base_from`/`upload_base_image`가 자동 제거.

---

## 6. 웹 편집기 매핑표 — 버튼 하나가 어디까지 가는가

> 웹 UI는 **버튼 → JS 함수 → API → `webapp.py` 함수 → 엔진** 순서로 흐른다. 문제가 생기면 이 순서대로 4단계를 짚어 내려간다.
> 모든 POST는 `api(path, body)` 헬퍼(JSON 전송 + 실패 시 toast)를 거친다.

| 탭 | 버튼 (화면 문구) | JS 함수 | API | 백엔드 | 최종 실행 |
|---|---|---|---|---|---|
| 공통 | 🔄 새로고침 | `loadState(true)` | `GET /api/state?force=1` | `build_state` | 상태+미리보기 재생성 |
| 공통 | 💾 상태 저장 | `saveStateFile()` | `POST /api/save_state` | `save_checkpoint_state` | checkpoint + 제목/설명 동기화 |
| 공통 | 💾 대본 저장 | `saveScript()` | `POST /api/script` | `save_script` | script.txt 저장 + 서명 갱신 + 빈 장면 플레이스홀더 |
| 공통 | (3초 폴링) | `pollJob()` | `GET /api/job` | `job_status` | ③탭 로그·진행 표시 |
| ① | 🤖 AI 대본 만들기 | `genScript()` | `POST /api/run` | `start_job` → `web_job.py` | `execute_spec` → `generate_text_content`(text_mode=all 등) |
| ① | 🧹 빈 문구 채우기 | `genFill()` | `POST /api/run` | 〃 | `text_mode=fill` (빈 대사·묘사만 AI 채움) |
| ① | ✍ 장면별 재작성 | `regen…` 계열 | `POST /api/run` | 〃 | `text_mode=scene` (장면 번호 지정) |
| ① | 🔄 Groq 모델 | `loadGroqModels()` | `GET /api/groq_models` | `TextGenerator.list_groq_models` | 모델 select 채움 |
| ① | ➕/▲▼/🗑/⏱ | `addScene/moveScene/removeScene/resequenceTime` | (로컬 상태만) | — | **💾 대본 저장 때 반영** |
| ① | 🔁 script.txt→체크포인트 | `syncNow()` | `POST /api/script_text` | `save_script(parse_script_text(text))` | 텍스트 영역 파싱 저장 |
| ② | 👁 미리보기(저장 안 함) | `previewSelected()` | `POST /api/preview` | `preview_scene` | `overlay.render_preview` |
| ② | 🖌 이 장면에 대사만 그리기 | `drawSelected()` | `POST /api/overlay/apply` | `apply_overlay_now` | `overlay.apply_scene` (SD/API 없음) |
| ② | 🎨 새 이미지 만들기 | `regenSceneImage(this)` | `POST /api/run` | `start_job` | `steps:["images","overlay"]`+`scenes.images=[n]` → SD/Gemini |
| ② | 🤖 이 장면 대사·묘사 다시 작성 | `regenSceneText()` | `POST /api/run` | 〃 | `text_mode=scene` |
| ② | 🎤 / 🔄 / 🔊 음성 | `regenSceneAudio/regenChangedAudio/regenAllAudio` | `POST /api/tts` | `regen_audio` | `generate_audio`+`merge_audio` (TTS) |
| ② | 💾 설정만 저장 | `saveCfg('none')` | `POST /api/overlay` | `save_overlay` | `overlay.save_config` (병합 저장) |
| ② | 🖌 모든 장면 대사 다시 그리기 | `saveCfg('all')` | `POST /api/overlay` | 〃 | 저장 + 전체 `apply_scene` |
| ② | ♻ 바뀐 장면만 대사 다시 그리기 | `saveCfg('auto')` | `POST /api/overlay` | 〃 | 저장 + 변경분만 `apply_scene` |
| ② | 🎨 모든 장면 이미지 다시 만들기 (AI) | `regenAllImages(this)` | `POST /api/run` | `start_job` | `scenes:{images:"all",overlay:"all"}` → 전체 SD/Gemini 생성 (확인창·예상시간, 버튼에 `7/13장·경과초` 진행률) |
| ② | 🖼 다른 이미지 올리기 | `uploadImage(this)` | `POST /api/upload_image` | `upload_base_image` | base 교체(`save_base_from`) + 텍스트 합성 |
| ② | 🖌 이 장면에 삽입 | `applyInsert()` | `POST /api/overlay/apply` | `apply_overlay_now` | 삽입 설정 합성 |
| ② | 💾 삽입 저장 + 즉시 반영 | `saveInsertCfg()` | `POST /api/overlay/apply` | 〃 | 〃 |
| ② | 🗑 삽입 제거 | `removeInsert()` | `POST /api/insert_image`(remove) | `remove_insert_image` | 삽입 파일 삭제 + 원본+텍스트 복원 |
| ③ | 🚀 제작 시작 | `startBuild()` | `POST /api/run` | `start_job` | 선택 단계 `execute_spec` (로그 ③탭) |
| ③ | ⏹ 작업 중지 | `stopBuild()` | `POST /api/job/stop` | `stop_job` | 워커 프로세스 종료 |
| ④ | 🎬 영상 생성 | `buildVideoNow()` | `POST /api/run` | 〃 | `steps:["video"]` |
| ④ | 📤 기존 영상 업로드 / 🎬+📤 | `uploadVideoNow(false/true)` | `POST /api/run` | 〃 | `steps:[…,"upload"]` |
| ④ | 💾 제목/설명 저장 | `saveTitles2()` | `POST /api/script` | `save_script` | script.txt 헤더 + checkpoint |
| — | 미디어 표시(썸네일/오디오/영상) | `<img>/<audio>/<video>` | `GET /media?path=…` | `_serve_media` | output 파일 스트리밍 |

**③탭 스펙(spec) 형태** — `/api/run`이 받는 JSON이 곧 엔진 입력:
```json
{ "steps": ["images","overlay"],           // 실행할 단계 (순서대로)
  "scenes": { "images": [3,7], "overlay": [13], "text": [], "tts": [] },  // 단계별 대상(빈 배열=전체)
  "image_mode": "sd_gguf",                 // sd_gguf | sd_sdxl | gemini | placeholder | skip
  "text_mode": "all",                      // all | script | fill | scene
  "sync": true, "speed": 1.0, "privacy": "unlisted", "label": "이미지 2장" }
```

> 🎨 이미지 버튼(`regenSceneImage`/`regenAllImages`)은 스펙에 `overlay` 키를 **넣지 않는다** — `overlay_config.json`을 덮어쓰지 않기 위함(§4 SoT 규칙 5).
> 작업 종료 판정은 `returncode` 하나에 의존하지 않고, 워커가 로그 끝에 남기는 `JOB_RESULT={"ok":…}`를 우선한다(§7 함정 #13).

---

## 7. 실제 사고 사례 & 재발 방지 규칙 (⚠️ 반복 금지)

이 프로젝트에서 **실제로 터졌던 버그**와 그 원인. 같은 실수를 다시 만들지 않는다.

| # | 사고 | 원인 (진짜) | 재발 방지 (코드에 반영됨) |
|---|---|---|---|
| 1 | 🎨 새 이미지 만들기를 눌러도 이미지가 그대로 | `create_placeholder_base`가 만든 **빈 원본이 실제 파일로 존재** → "파일 있음 = 생성됨" 게이트가 스킵 | `.placeholder` 표식 파일 + `overlay.is_placeholder` + UI `임시` 배지/경고 |
| 2 | SD 이미지 생성이 **조용히** 실패 | 웹서버가 **시스템 파이썬**(torch 없음)으로 실행됨 | `/api/state.torch_available`, `start_job` 사전 차단, ②탭 `torch-warn` 배너, `start_web.bat`(venv) |
| 3 | 같은 포트에 서버가 **2개** 떠서 요청이 엉뚱한 인스턴스로 감 | `ThreadingHTTPServer`가 Windows에서 `SO_REUSEADDR=True`로 이중 바인딩 허용 | `_SingleInstanceHTTPServer(allow_reuse_address=False)` + "이미 실행 중" 안내 후 종료 |
| 4 | 버튼을 눌러도 **아무 반응 없음** 신고 | JS가 조건에서 **조용히 return** | `saveScript`가 `{ok:false,error:'job-running'}` 반환 → toast로 사유 표시 |
| 5 | 버튼 의미 혼동(🎨 vs 🖌) | 라벨이 애매 | 🎨=AI 실제 생성, 🖌=`…대사만 그리기 (AI 아님)` 로 문구 고정 |
| 6 | 설정이 사용자 동의 없이 바뀐 것처럼 보임 | `overlay_config.json`은 **②탭 슬라이더 값이 곧 저장값**이고, 스펙(`spec.overlay`)으로도 쓰임 | 설정 변경은 ②탭에서만, `save_config`는 **부분 병합**(넘어온 키만 갱신) |
| 7 | 대사만 고쳤는데 영상에 옛 대사 | 영상 단계가 overlay 재합성 없이 진행 | `plan_tasks`가 `overlay_sig ≠ scene_sig.content`면 `image_overlay`로 잡고, 영상 전에 재합성 |
| 8 | 장면을 추가/저장했더니 장면이 사라짐 | 파서가 빈 장면을 버림 | `parse_script_text`가 빈 장면을 보존, `save_script`가 플레이스홀더 원본 생성 |
| 9 | 원본(base)이 회색·단색으로 오염 | SD 실패 산출물을 원본으로 승격 | `is_suspect_image` 검사 + 생성 실패 시 기존 파일 보존 |
| 10 | `start_web.bat` 실행 오류 | 배치 파일에 한글 → cmd 파서 깨짐 | `.bat`은 **ASCII 전용** 유지 |
| 11 | ②탭 버튼 글씨가 **안 보임**(흰 바탕에 흰 글씨) | 다크 테마 화면에 **밝은 배경 박스**(`#f8fafc`) 안에 `.ghost` 버튼(투명 배경)을 넣음 | UI 추가 시 **테마 변수만 사용**(`var(--panel2)`/`var(--line)`/`var(--txt)`), 밝은 배경 박스 금지 |
| 12 | 같은 동작 버튼이 2개(🖌 전체 대사 다시 그리기 ×2) | `applyNow()`와 `saveCfg('all')`이 동일 기능 | 중복 제거, 그 자리를 **🎨 모든 장면 이미지 다시 만들기(AI)** 로 교체 |
| 13 | 이미지 13장을 **정상 생성**했는데 `⚠️ 일부 장면 생성에 실패했습니다` | 폴러가 `returncode`만 보고 판정 → `api()`가 `{ok:false}`(응답 해석 실패)를 반환하거나 `returncode`가 아직 `null`인 순간을 "끝남 + 실패"로 오판 | `jobVerdict()` 신설 — 로그 끝 `JOB_RESULT` 우선, 판정 불가면 **보류 후 재확인**(실패로 단정 금지). 버튼에 `7/13장·경과초` 진행률 표시 |
| 14 | '대본 생성' 완료/오류 문구가 **엉뚱한 작업**에서 뜸 | 전역 `pollJob()`이 `S.jobRunning`만 보고 모든 작업을 'AI 대본 생성'으로 처리 | `S.jobOwner`(`'script'`/`'image'`)로 소유자 구분 — 대본 전용 UI·문구는 `owner==='script'`일 때만, 그 외엔 `🎉 <라벨> 완료` |

---

## 8. 새 기능을 추가할 때 체크리스트

1. **규칙은 엔진에** — `modules/pipeline.py`(단계) 또는 해당 모듈(텍스트/이미지/TTS/합성)에 구현. UI에만 만들지 않는다.
2. **스펙 키 결정** — `steps`(단계명)·`scenes`(대상 장면)·`mode`(동작 방식). CLI와 웹이 같은 키를 쓰게 한다.
3. **웹이면 3곳** — ⑴ 버튼/입력 (`index.html`) ⑵ `api()` 호출 함수 ⑶ 필요시 `spec` 조립(`startBuild`/`videoSpec`). **②탭과 ③탭의 모델 select 옵션은 둘 다** 갱신(한쪽만 고치면 안 보임).
4. **상태 반영** — 작업 완료 시 `mark_assets`/`mark_overlay_applied(_map)`/`mark_video_built` 호출. **파일이 실제로 존재할 때만**.
5. **서명 영향 확인** — 새 설정이 합성 결과에 영향을 주면 `overlay.DEFAULT_CONFIG`(또는 `DEFAULT_INSERT`)에 키 등록 → 자동으로 재합성 감지.
6. **UI 노출** — `build_state`에 정보 추가(배지·경고·미리보기 URL 등) + `render*Panel()` 반영.
7. **테스트** — `test/` 에 신규 테스트 추가 + 기존 회귀 실행(§9 명령). 모의(mock)로 네트워크/SD 호출 없이.
8. **문서** — 이 파일의 §3(매트릭스)·§6(매핑표) 갱신 + `프로젝트_진행_내역.md`에 사고/원인/수정/검증 기록.

---

## 9. 실행 · 검증 명령 (PowerShell · 작업 폴더 `<project>`)

> ⚠️ **항상 venv 파이썬**(`<project>\venv\Scripts\python.exe`)을 쓴다. 시스템 파이썬은 torch가 없다.

```powershell
# 1) 문법 검사 (수정 직후 습관처럼)
<project>\venv\Scripts\python.exe -m py_compile webapp.py modules\overlay.py modules\pipeline.py modules\script_store.py

# 2) 회귀 테스트 — 각 테스트는 단독 실행 스크립트 (실패 시 예외 중단)
<project>\venv\Scripts\python.exe test\test_overlay.py      # 개별 실행
Get-ChildItem test\test_*.py | ForEach-Object { <project>\venv\Scripts\python.exe $_.FullName }   # 전체

# 3) 웹 편집기 실행 (venv · torch 포함)
<project>\start_web.bat                                     # 더블클릭 대신 이것 (권장)
<project>\venv\Scripts\python.exe webapp.py --open          # 직접 실행

# 4) 서버 상태 점검 (torch 여부 · 장면 수 · 임시 이미지 목록)
(Invoke-RestMethod 'http://127.0.0.1:8765/api/state').torch_available
(Invoke-RestMethod 'http://127.0.0.1:8765/api/state').count
(Invoke-RestMethod 'http://127.0.0.1:8765/api/state').scenes | Where-Object is_placeholder | Select-Object scene

# 5) 포트 점유 진단 (이중 실행 의심 시)
Get-NetTCPConnection -LocalPort 8765 -State Listen | Select-Object OwningProcess
Get-Process -Id (Get-NetTCPConnection -LocalPort 8765 -State Listen).OwningProcess | Select-Object Id, Path

# 6) 작업 로그 실시간 (Ctrl+C 로 종료)
Get-Content output\web_job.log -Tail 40 -Wait

# 7) 테스트 격리 실행 (실제 output 오염 방지)
$env:SAAS_OUTPUT_DIR = "$PWD\output_test"; <project>\venv\Scripts\python.exe webapp.py --port 8899
```

---

## 10. 용어 사전

| 용어 | 뜻 |
|---|---|
| **장면(scene)** | `{time, content, visual}` 한 덩어리. content=대사(음성·자막), visual=시각 묘사(이미지 프롬프트) |
| **원본 / base** | `images/base/scene_XX.png` — AI가 그린 텍스트 없는 그림. 재합성의 근거 |
| **최종본** | `images/scene_XX.png` — base + 대사(+삽입) 합성 결과. 영상에 들어감 |
| **서명(signature)** | 대사·묘사의 해시. 변경 감지의 기준값 (`scene_signature`, `overlay.current_key`) |
| **기준선** | "이 자산을 마지막으로 만들었을 때"의 서명 (`img_sig`/`audio_sig`/`video_sig`/`overlay_sig`) |
| **스펙(spec)** | `/api/run`에 전달되는 작업 JSON (§6 하단). 웹·워커·엔진이 공유하는 계약 |
| **단계(step)** | `text` · `images` · `overlay` · `tts` · `video` · `upload` |
| **범위(scope)** | `scenes`의 대상 배열. **빈 배열 = 전체 장면**. overlay의 `apply`는 `none`(저장만)/`auto`(변경분)/`all`(전체) |
| **플레이스홀더** | 빈 장면용 임시 이미지. `.placeholder` 표식이 있으면 "실제 AI 이미지 아님" |
| **이미지 모드** | `sd_gguf`(권장) · `sd_sdxl` · `gemini` · `placeholder`(임시) · `skip`(기존 유지) |
| **text_mode** | `all`(제목+대본) · `script`(대본만) · `fill`(빈 문구만 채움) · `scene`(특정 장면 재작성) |
| **배지** | 장면 목록 표시: `없음`/`임시`/`재생성`/`텍스트`/`한자`/`원본 이상` |
| **워커(worker)** | `scripts/web_job.py` — 웹이 띄우는 실제 작업 프로세스(로그는 `web_job.log`) |

---

## 📌 이 문서를 유지하는 규칙

1. **코드를 고치면 이 문서를 같이 고친다.** 최소한 §3(매트릭스)·§6(매핑표)는 수정 직후 반영.
2. **새 사고(버그)가 나면 §7 표에 한 줄 추가** — 증상 / 진짜 원인 / 재발 방지.
3. **문서는 이 파일 하나만 유지한다.** 같은 내용을 `사용법_설명서.md`(사용자용)·`README.md`(설치/소개)에 중복 서술하지 않는다.
4. 문서 말미의 **최종 갱신 날짜**를 바꾼다.





