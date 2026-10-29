<!-- 생성: 2026-10-29 21:36 KST -->

# 팀 프로젝트 팀 편성 웹 앱 (중간 과제)

학생이 팀에 지원하고 팀원이 투표해 팀을 꾸리는 Streamlit 웹 앱. 모집을 마감한 뒤 팀이 없는 학생은 오픈라우터의 AI가 배정안을 내고, 앱이 그 배정안을 규칙으로 검사한다.

- 작성자: 김보빈

## 1. 배포 주소

(배포 뒤 채움)

## 2. PRD와 구현 계획의 위치

- PRD: [docs/PRD.md](docs/PRD.md)
- 구현 계획: [docs/구현 계획.md](docs/구현%20계획.md)
- DB 테이블: [schema.sql](schema.sql)

## 3. 고른 해결 방법

공고 3장의 기능 8개를 모두 어려운 해결로 만들었다.

| 기능 | 고른 해결 | 구현 위치 |
|---|---|---|
| 다른 사람의 변경 보기 | 어려운 해결(`st.fragment(run_every=2)`로 팀 목록, 지원, 투표 단추, 팀이 없는 학생을 2초마다 다시 그림) | `streamlit_app.py`의 `student_board`, `admin_board` |
| 필수 포함 역할을 지킬 수 없는 팀 | 어려운 해결(지원 단계에서 필수 포함 역할을 채울 자리가 모자라게 되는 지원을 막음) | `rules.required_slot_ok`, `rules.apply_block_reason` |
| 같은 팀에 대기 중인 지원이 여럿 | 어려운 해결(승인 직전에 정원, 주 역할 중복, 필수 포함 역할 자리를 다시 검사함. 투표가 끝난 순서로 처리) | `rules.recheck_reason`, `service.vote` |
| 마지막 자리에 두 명이 동시에 들어감 | 어려운 해결(DB 유일성 제약: `tf_members`의 기본 키 `(team_id, slot_no)`, `student_id` 유일, 대기 지원 학생당 1개) | `schema.sql` |
| AI 응답이 늦을 때 | 어려운 해결(모델마다 부른 때부터 응답을 다 받을 때까지 120초 전체 대기 시간을 재서 끊고 다음 모델로 넘어감) | `ai.call_with_deadline`, `ai.run_assignment` |
| 3차 모델까지 실패 | 어려운 해결(검사 다섯 가지를 모두 통과하는 배정을 모든 경우를 따져 끝까지 찾음. 배정이 없으면 이유를 보여 줌) | `rules.find_assignment`, `rules.infeasibility_reasons` |
| AI 대기 중 화면 | 어려운 해결(`assign_status`에 "2차 모델(…)의 응답을 기다리는 중 (35초 / 120초)"처럼 몇 차 모델을 몇 초째 기다리는지 1초마다 보여 줌) | `streamlit_app._run_assign` |
| DB(Supabase)가 일시정지되지 않게 | 어려운 해결(외부 예약 서비스인 GitHub Actions가 매일 한국 시각 09:00에 DB에 질의를 보냄) | `.github/workflows/keep-db-awake.yml` |

## 4. 쓴 모델 3개

- 1차 `cohere/north-mini-code:free`
- 2차 `poolside/laguna-s-2.1:free`
- 3차 `google/gemma-4-31b-it:free`

2026-10-29 저녁에 무료 모델 13개를 어려움 시나리오의 마감 직후 상태로 시험해, 규칙을 지키는 배정안을 낸 모델과 빠르게 답한 모델 가운데 서로 다른 회사의 모델을 골랐다(시험 기록: [docs/사례 기록.md](docs/사례%20기록.md)).

## 5. 오픈라우터 AI 모델 호출 실패 사례

(배포 뒤 화면과 함께 채움)

## 6. 클로드가 잘못된 추론이나 답변을 한 사례

(채움)

## 7. 앱에서 발견한 문제점이나 개선 필요 사항

(채움)

## 실행 방법(내 컴퓨터)

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

`.env`에 `OPENROUTER_API_KEY`, `DATABASE_URL`(Supabase Session pooler), `ADMIN_PASSWORD`를 넣는다. 값은 커밋하지 않는다.

테스트: `python -m pytest -q`
