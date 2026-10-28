# 생성: 2026-10-28 19:43 KST
"""AI 배정(PRD 6장). 오픈라우터의 무료 텍스트 모델 3개를 1차, 2차, 3차로 부르고,
모델마다 부른 때부터 응답을 다 받을 때까지 120초를 넘기면 끊고 다음 모델로 넘어간다.
3차까지 실패하면 앱이 모든 경우를 따져 찾은 배정을 쓴다."""

import json
import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import requests

from rules import PL, ROLES, WP, Student, Teams, find_assignment, infeasibility_reasons, validate_plan

API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEADLINE_SEC = 120

# Task 7에서 실제 호출 시험으로 정한다.
MODELS = (
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-chat-v3-0324:free",
    "qwen/qwen3-235b-a22b:free",
)


class AIError(Exception):
    pass


@dataclass
class AssignResult:
    plan: dict[str, int] | None
    source: str
    failures: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def _person(s: Student) -> dict:
    return {"student_no": s.student_no, "name": s.name, "main_role": s.main_role, "sub_roles": list(s.sub_roles)}


def build_messages(teams: Teams, unassigned: Sequence[Student]) -> list[dict]:
    state = {
        "teams": [{"team": t, "members": [_person(m) for m in teams[t]]} for t in sorted(teams)],
        "unassigned_students": [_person(s) for s in unassigned],
    }
    rules = (
        f"역할은 {', '.join(ROLES)}의 6개다. 학생마다 주 역할 1개와 보조 역할 0~2개가 있다.\n"
        "규칙:\n"
        "1. 팀이 없는 학생(unassigned_students)을 빠짐없이 한 팀에만 배정한다.\n"
        "2. 이미 팀에 있는 학생은 옮기지 않는다. 배정안에는 팀이 없는 학생만 적는다.\n"
        "3. 배정 뒤 모든 팀은 2~4명이어야 한다(빈 팀 없음).\n"
        "4. 한 팀 안에 주 역할이 같은 학생이 2명 이상이면 안 된다(보조 역할은 중복을 따지지 않는다).\n"
        f"5. 모든 팀에 {PL} 역할 학생과 {WP} 역할 학생이 서로 다른 사람으로 1명씩 있어야 한다. "
        "주 역할이나 보조 역할로 맡을 수 있다. 한 학생이 둘 다 맡을 수는 없다.\n"
    )
    answer_format = (
        '답은 아래 모양의 JSON 하나만 쓴다. 설명은 쓰지 않는다.\n'
        '{"assignments": [{"student_no": "학번", "team": 팀번호}, ...]}'
    )
    return [
        {"role": "system", "content": "너는 대학 팀 프로젝트의 팀 배정을 돕는다. 규칙을 모두 지키는 배정안을 JSON으로만 답한다."},
        {"role": "user", "content": rules + "\n지금 상태(JSON):\n"
         + json.dumps(state, ensure_ascii=False) + "\n\n" + answer_format},
    ]


def _team_no(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    m = re.search(r"\d+", str(value))
    return int(m.group()) if m else None


def _pairs(data) -> list[tuple[str, int]] | None:
    if isinstance(data, dict):
        data = data.get("assignments")
    if isinstance(data, dict):  # {"학번": 팀} 모양
        data = [{"student_no": k, "team": v} for k, v in data.items()]
    if not isinstance(data, list) or not data:
        return None
    pairs = []
    for item in data:
        if not isinstance(item, dict) or "student_no" not in item or "team" not in item:
            return None
        team = _team_no(item["team"])
        if team is None:
            return None
        pairs.append((str(item["student_no"]).strip(), team))
    return pairs


def parse_assignments(text: str) -> list[tuple[str, int]] | None:
    """응답에서 배정안 JSON을 꺼낸다. 코드 블록 표시나 앞뒤 설명이 섞여 있어도 읽는다."""
    if not text:
        return None
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch not in "{[":
            continue
        try:
            data, _ = decoder.raw_decode(text, i)
        except ValueError:
            continue
        if isinstance(data, dict) and "assignments" not in data:
            continue
        pairs = _pairs(data)
        if pairs is not None:
            return pairs
    return None


def call_openrouter(model: str, messages: list[dict], api_key: str) -> str:
    try:
        resp = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": messages,
                "reasoning": {"effort": "low"},
                "max_tokens": 8000,
                "temperature": 0,
            },
            timeout=(10, DEADLINE_SEC + 10),
        )
    except requests.RequestException as e:
        raise AIError(f"연결 오류({type(e).__name__})") from None
    if resp.status_code != 200:
        raise AIError(f"HTTP {resp.status_code}")
    try:
        body = resp.json()
    except ValueError:
        raise AIError("응답이 JSON이 아님") from None
    if body.get("error"):
        code = body["error"].get("code", "") if isinstance(body["error"], dict) else ""
        raise AIError(f"오류 응답 {code}".strip())
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        content = None
    if not content or not str(content).strip():
        raise AIError("빈 응답")
    return str(content)


def call_with_deadline(fn: Callable[[], str], deadline_sec: float, on_tick: Callable[[float], None]) -> str:
    """fn을 데몬 스레드에서 돌리고, deadline_sec이 지나면 기다리지 않고 AIError를 던진다.
    with ThreadPoolExecutor()는 빠져나갈 때 스레드를 기다려 제한 시간이 깨지므로 쓰지 않는다."""
    box: dict = {}
    done = threading.Event()

    def work():
        try:
            box["v"] = fn()
        except BaseException as e:
            box["e"] = e
        finally:
            done.set()

    threading.Thread(target=work, daemon=True).start()
    start = time.monotonic()
    while not done.wait(timeout=min(1.0, max(0.0, deadline_sec - (time.monotonic() - start)))):
        elapsed = time.monotonic() - start
        if elapsed >= deadline_sec:
            raise AIError(f"{int(deadline_sec)}초 안에 응답 없음")
        on_tick(elapsed)
    if "e" in box:
        raise box["e"]
    return box["v"]


def run_assignment(teams: Teams, unassigned: Sequence[Student], *,
                   call_model: Callable[[str], str],
                   models: Sequence[str] = MODELS,
                   deadline_sec: float = DEADLINE_SEC,
                   on_progress: Callable[[str], None],
                   log: Callable[[int, str, str, str, float], None]) -> AssignResult:
    fallback = find_assignment(teams, unassigned)
    if fallback is None:
        return AssignResult(None, "", [], infeasibility_reasons(teams, unassigned))
    if not unassigned:
        return AssignResult({}, "배정할 학생 없음")

    current = {m.student_no: t for t, ms in teams.items() for m in ms}
    failures: list[str] = []
    for i, model in enumerate(models, start=1):
        def tick(elapsed, i=i, model=model):
            on_progress(f"{i}차 모델({model})의 응답을 기다리는 중 ({int(elapsed)}초 / {int(deadline_sec)}초)")

        tick(0)
        start = time.monotonic()
        try:
            text = call_with_deadline(lambda model=model: call_model(model), deadline_sec, tick)
            pairs = parse_assignments(text)
            if pairs is None:
                raise AIError("배정안을 JSON으로 읽을 수 없음")
            # 이미 팀에 있는 학생을 원래 팀 그대로 적은 줄은 옮긴 것이 아니므로 뺀다. 다른 팀에 적었으면 검사에서 걸린다.
            pairs = [(no, t) for no, t in pairs if current.get(no) != t]
            errors = validate_plan(teams, unassigned, pairs)
            if errors:
                raise AIError("검사 통과 못 함: " + "; ".join(errors[:3]))
        except Exception as e:
            reason = str(e) if isinstance(e, AIError) else f"오류({type(e).__name__})"
            failures.append(f"{i}차 모델({model}) 실패: {reason}")
            log(i, model, "실패", reason, time.monotonic() - start)
            continue
        log(i, model, "성공", "", time.monotonic() - start)
        return AssignResult(dict(pairs), f"{i}차 모델 {model}", failures)

    return AssignResult(fallback, "앱 자체 배정", failures)
