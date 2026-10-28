<!-- 생성: 2026-10-28 19:36 KST -->

# CLAUDE.md

팀 프로젝트 팀 편성 웹 앱(중간 과제). 요구사항은 `docs/PRD.md`, 작업 순서는 `docs/구현 계획.md`에 있다.

## 키 관리

- `.env`의 `OPENROUTER_API_KEY`, `DATABASE_URL`, `ADMIN_PASSWORD` 값을 화면, 로그, 커밋, 예외 안내에 절대 출력하지 않는다.
- 키가 있는지 확인할 때는 "있음, 없음"만 출력한다.
- `.env`를 읽거나 내용을 보여 주는 명령(`cat .env` 등)을 쓰지 않는다.
- 코드는 `config.get_secret(이름)`으로만 키를 읽는다.

## 명령

- 테스트: `python -m pytest -q`
- 실행: `streamlit run streamlit_app.py`

## 규칙

- `result` 안내는 `승인: `, `대기: `, `거절: `, `막힘: ` 가운데 하나로 시작한다.
- 화면 key는 `docs/PRD.md` 7.2절 표와 한 글자도 다르면 안 된다.
- 테이블 이름은 모두 `tf_`로 시작한다.
- 클로드의 잘못, AI 호출 실패, 앱의 문제를 발견하면 `docs/사례 기록.md`에 날짜와 근거(커밋, 화면)를 함께 적는다.
