# -*- coding: utf-8 -*-
"""웹 편집기(webapp.py) 스모크 테스트 — 서버 기동 + 주요 API 확인 (이미지 생성 없음)

사용: .\\venv\\Scripts\\python.exe -X utf8 scripts\\test_webapp.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PORT = 8899
BASE = f"http://127.0.0.1:{PORT}"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return r.status, r.read().decode("utf-8")


def get_status(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return r.status, r.read()


def post(path, payload):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    # ---- 실제 output 보호: 임시 폴더에서 서버를 띄운다 (SAAS_OUTPUT_DIR) ----
    #  예전에는 실제 output 으로 서버가 떠서, 시작 시 base 자동 승격(sync_missing_bases)과
    #  설정파일 백업/복원이 사용자 작업물과 충돌했다. (2026-09-23 원인 규명)
    tmp = Path(tempfile.mkdtemp(prefix="saas_webapp_"))
    (tmp / "images").mkdir(parents=True, exist_ok=True)
    (tmp / "audio").mkdir(parents=True, exist_ok=True)
    (tmp / "script.txt").write_text(
        "[장면 1] 0~5초\n  내용: 스모크 테스트 장면 하나\n  시각: 테스트 배경 하나\n\n"
        "[장면 2] 5~10초\n  내용: 스모크 테스트 장면 둘\n  시각: 테스트 배경 둘\n",
        encoding="utf-8")
    try:  # 미리보기 렌더용 이미지(base + final)
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (1080, 1920), (210, 220, 235))
        ImageDraw.Draw(im).rectangle([0, 1300, 1080, 1920], fill=(60, 90, 160))
        im.save(tmp / "images" / "scene_01.png")
        (tmp / "images" / "base").mkdir(parents=True, exist_ok=True)
        im.save(tmp / "images" / "base" / "scene_01.png")
    except Exception:
        pass
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["SAAS_OUTPUT_DIR"] = str(tmp)
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", str(ROOT / "webapp.py"), "--port", str(PORT)],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    try:
        ready = False
        for _ in range(40):
            time.sleep(0.5)
            try:
                get("/api/state")
                ready = True
                break
            except Exception:
                continue
        assert ready, "웹 서버가 20초 안에 시작되지 않았습니다"
        print("[1] ✅ 서버 기동")

        code, html = get("/")
        assert code == 200 and "쇼츠 웹 편집기" in html, "HTML 페이지 응답 이상"
        print(f"[2] ✅ HTML 페이지 로드 ({len(html):,} bytes)")

        st = json.loads(get("/api/state")[1])
        assert st["ok"] and "scenes" in st and "overlay" in st and "plan" in st, st
        print(f"[3] ✅ /api/state → 장면 {st['count']}개 / 체크포인트 {st['checkpoint']}")

        res = post("/api/overlay", {"config": st["overlay"], "apply": "none"})
        assert res["ok"], res
        print("[4] ✅ /api/overlay 설정 저장(적용 없음)")

        if st["count"]:
            res2 = post("/api/preview", {"scene": 1, "text": "미리보기 테스트 대사"})
            assert res2["ok"] and res2["url"], res2
            code2, body = get_status(res2["url"])
            assert code2 == 200 and body[:4] == b"\x89PNG", "미리보기 이미지 응답 이상"
            print(f"[5] ✅ /api/preview 미리보기 렌더 + /media 제공 ({len(body):,} bytes PNG)")
        else:
            print("[5] ⚠ script.txt 에 장면이 없어 미리보기 테스트는 생략")

        try:
            get("/media?path=../config.py")
            raise AssertionError("경로 탈출이 차단되지 않음")
        except urllib.error.HTTPError as e:
            assert e.code in (403, 404), e.code
            print("[6] ✅ 프로젝트 밖 경로 접근 차단 확인")

        j = json.loads(get("/api/job")[1])
        assert "running" in j, j
        print(f"[7] ✅ /api/job 상태 조회 (running={j['running']})")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
        # 임시 폴더 정리 (실제 output 은 건드리지 않음)
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    main()
    print("\n🎉 웹 편집기 스모크 테스트 통과")
