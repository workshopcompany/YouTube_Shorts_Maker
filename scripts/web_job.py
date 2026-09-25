# -*- coding: utf-8 -*-
"""웹 편집기(webapp.py)가 백그라운드로 실행하는 제작 작업 워커.

사용: python -u -X utf8 scripts\\web_job.py <spec.json>
spec.json 은 modules/pipeline.execute_spec() 스펙(JSON)이며,
진행 로그는 표준출력으로, 결과는 마지막 줄 JOB_RESULT=<json> 으로 나온다.

SAAS_OUTPUT_DIR 환경변수가 있으면 그 폴더를 output 으로 사용한다(테스트/격리 모드).
"""
import json
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main() -> int:
    if len(sys.argv) < 2:
        print("사용법: python -X utf8 scripts/web_job.py <spec.json>")
        return 2
    spec_path = Path(sys.argv[1])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    # 격리 모드 — 부모(webapp.py)가 지정한 output 폴더를 그대로 사용
    env_out = os.environ.get("SAAS_OUTPUT_DIR")
    if env_out:
        from modules import script_store, overlay as overlay_mod
        script_store.set_output_dir(env_out)
        overlay_mod.OUTPUT_DIR = str(env_out)

    print(f"🚀 작업 시작 (단계: {spec.get('steps')})", flush=True)

    from modules import pipeline

    def log(msg=""):
        print(msg, flush=True)

    try:
        result = pipeline.execute_spec(spec, log=log)
    except KeyboardInterrupt:
        print("⚠️ 사용자가 작업을 중단했습니다.", flush=True)
        return 130
    except Exception:
        traceback.print_exc()
        print("JOB_RESULT=" + json.dumps({"ok": False, "error": "예외 발생"}, ensure_ascii=False),
              flush=True)
        return 1

    print("JOB_RESULT=" + json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
