## 변경 내용

- 

## 체크리스트

- [ ] `python -m py_compile` 로 수정 파일 문법 검사 통과
- [ ] `test\test_*.py` 회귀 테스트 실행 (모델·API 없이 돌아가는 것만)
- [ ] **비밀값 미포함** 확인 (`config.py` 에 실제 키 없음, `.env`/`token.pickle`/`client_secret.json` 커밋 안 함)
- [ ] 절대경로 하드코딩 없음 (드라이브 문자 경로 / 개인 사용자 폴더 경로 금지)
- [ ] 문서 갱신 (README / 사용법_설명서.md / ARCHITECTURE.md)
- [ ] `.bat` 파일은 **ASCII only** (한글 + chcp 65001 은 cmd 파서를 깨뜨림)

## 테스트 방법

```
# 재현/검증 명령을 적어주세요
```

## 스크린샷 / 로그 (선택)
