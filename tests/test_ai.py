# 생성: 2026-10-28 19:43 KST
import json
import time

import pytest

import ai
from ai import AIError, build_messages, call_openrouter, call_with_deadline, parse_assignments, run_assignment
from rules import PL, WP, Student, find_assignment, validate_plan
from tests.states import hard_after_close

QUIET = dict(on_progress=lambda s: None, log=lambda *a: None)


def _raise_or(value):
    if isinstance(value, Exception):
        raise value
    return value


def _good_json(teams, unassigned):
    plan = find_assignment(teams, unassigned)
    return json.dumps({"assignments": [{"student_no": k, "team": v} for k, v in plan.items()]})


def test_parse_variants():
    assert parse_assignments('```json\n{"assignments":[{"student_no":"2026303","team":3}]}\n```') == [("2026303", 3)]
    assert parse_assignments('배정안입니다: {"assignments":[{"student_no":2026303,"team":"3"}]} 끝') == [("2026303", 3)]
    assert parse_assignments('{"assignments":[{"student_no":"2026303","team":"팀3"}]}') == [("2026303", 3)]
    assert parse_assignments('생각: {"x": 1} 답: {"assignments":[{"student_no":"1","team":2}]}') == [("1", 2)]
    assert parse_assignments("모르겠어요") is None
    assert parse_assignments('{"assignments":[{"student_no":"1"}]}') is None
    assert parse_assignments("") is None


def test_build_messages_carries_state_and_rules():
    teams, unassigned = hard_after_close()
    text = json.dumps(build_messages(teams, unassigned), ensure_ascii=False)
    for s in unassigned:
        assert s.student_no in text and s.name in text
    assert "학생1(PL;RW)" in text                    # 지금 팀 구성도 보냄
    for word in ("2~4명", "주 역할", "기획자", "웹 프로그래머", "옮기지", "assignments"):
        assert word in text
    assert "1234" not in text and "password" not in text
    content = build_messages(teams, unassigned)[1]["content"]
    data = json.loads(content.split("지금 상태(JSON):\n")[1].split("\n\n")[0])
    by_team = {t["team"]: t for t in data["teams"]}
    assert by_team[1]["free_slots"] == 1 and by_team[3]["free_slots"] == 2 and by_team[4]["free_slots"] == 4
    assert by_team[4]["must_add_at_least"] == 2 and by_team[1]["must_add_at_least"] == 0


def test_deadline_cuts_slow_model():
    t0 = time.monotonic()
    with pytest.raises(AIError, match="응답 없음"):
        call_with_deadline(lambda: time.sleep(5) or "x", 1.0, lambda e: None)
    assert time.monotonic() - t0 < 2.0


def test_deadline_ticks_every_second_and_returns_value():
    ticks = []
    assert call_with_deadline(lambda: time.sleep(2.2) or "ok", 10, ticks.append) == "ok"
    assert len(ticks) >= 2


def test_deadline_passes_errors_through():
    with pytest.raises(AIError, match="HTTP 429"):
        call_with_deadline(lambda: _raise_or(AIError("HTTP 429")), 5, lambda e: None)


def test_falls_through_to_second_then_app():
    teams, unassigned = hard_after_close()
    good = _good_json(teams, unassigned)
    bad = json.dumps({"assignments": [{"student_no": s.student_no, "team": 4} for s in unassigned]})
    calls = iter([AIError("HTTP 429"), good])
    r = run_assignment(teams, unassigned, call_model=lambda m: _raise_or(next(calls)),
                       models=("a", "b", "c"), deadline_sec=2, **QUIET)
    assert r.source == "2차 모델 b" and len(r.failures) == 1
    assert r.failures[0] == "1차 모델(a) 실패: HTTP 429"
    assert validate_plan(teams, unassigned, list(r.plan.items())) == []
    r = run_assignment(teams, unassigned, call_model=lambda m: bad, models=("a", "b", "c"), deadline_sec=2, **QUIET)
    assert r.source == "앱 자체 배정" and len(r.failures) == 3
    assert all("검사" in f for f in r.failures)
    assert validate_plan(teams, unassigned, list(r.plan.items())) == []


def test_timeout_moves_to_next_model():
    teams, unassigned = hard_after_close()
    good = _good_json(teams, unassigned)
    progress = []

    def call(model):
        if model == "slow":
            time.sleep(5)
        return good

    t0 = time.monotonic()
    r = run_assignment(teams, unassigned, call_model=call, models=("slow", "fast", "c"),
                       deadline_sec=1.5, on_progress=progress.append, log=lambda *a: None)
    assert time.monotonic() - t0 < 3.5
    assert r.source == "2차 모델 fast"
    assert len(r.failures) == 1 and r.failures[0].startswith("1차 모델(slow) 실패: ")
    assert "응답 없음" in r.failures[0]
    assert any(p.startswith("1차 모델(slow)의 응답을 기다리는 중") for p in progress)
    assert any(p.startswith("2차 모델(fast)의 응답을 기다리는 중") for p in progress)


def test_no_ai_call_when_infeasible():
    full = [Student(str(i), f"s{i}", r) for i, r in enumerate([PL, "테스터", "발표자", "보고서 작성자"])]
    teams = {1: full, 2: [], 3: []}
    unassigned = [Student("a", "a", WP), Student("b", "b", PL), Student("c", "c", WP), Student("d", "d", PL)]

    def must_not_call(model):
        raise AssertionError("AI를 부르면 안 됨")

    r = run_assignment(teams, unassigned, call_model=must_not_call, models=("a", "b", "c"), deadline_sec=1, **QUIET)
    assert r.plan is None and r.reasons and "팀1에 웹 프로그래머를 맡을 학생이 없음" in r.reasons


def test_empty_and_http_errors_are_failures():
    teams, unassigned = hard_after_close()
    outcomes = iter([AIError("빈 응답"), AIError("HTTP 500"), "JSON이 아닌 글"])
    logged = []
    r = run_assignment(teams, unassigned, call_model=lambda m: _raise_or(next(outcomes)),
                       models=("a", "b", "c"), deadline_sec=2, on_progress=lambda s: None,
                       log=lambda *a: logged.append(a))
    assert r.source == "앱 자체 배정"
    assert [f.split(": ", 1)[1] for f in r.failures] == ["빈 응답", "HTTP 500", "배정안을 JSON으로 읽을 수 없음"]
    assert [(a[0], a[1], a[2]) for a in logged] == [(1, "a", "실패"), (2, "b", "실패"), (3, "c", "실패")]


def test_unexpected_exception_is_a_failure_not_a_crash():
    teams, unassigned = hard_after_close()
    r = run_assignment(teams, unassigned, call_model=lambda m: _raise_or(ValueError("x")),
                       models=("a", "b", "c"), deadline_sec=2, **QUIET)
    assert r.source == "앱 자체 배정" and len(r.failures) == 3


def test_nothing_to_assign_needs_no_ai():
    teams = {1: [Student("1", "1", PL), Student("2", "2", WP)], 2: [Student("3", "3", PL), Student("4", "4", WP)]}
    r = run_assignment(teams, [], call_model=lambda m: _raise_or(AssertionError()), models=("a", "b", "c"),
                       deadline_sec=1, **QUIET)
    assert r.plan == {} and r.reasons == []


def test_models_are_three_and_not_the_free_router():
    assert len(ai.MODELS) == 3 and len(set(ai.MODELS)) == 3
    assert all(m != "openrouter/free" and not m.startswith("openrouter/") for m in ai.MODELS)


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _fake_post(resp, seen):
    def post(url, headers=None, json=None, timeout=None):
        seen.update(url=url, headers=headers, json=json, timeout=timeout)
        return resp
    return post


def test_call_openrouter_request_and_errors(monkeypatch):
    seen = {}
    ok = _Resp(200, {"choices": [{"message": {"content": "답"}}]})
    monkeypatch.setattr(ai.requests, "post", _fake_post(ok, seen))
    assert call_openrouter("m/x:free", [{"role": "user", "content": "q"}], "KEY123") == "답"
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer KEY123"
    assert seen["json"]["model"] == "m/x:free"
    assert seen["json"]["reasoning"] == {"effort": "low"}
    assert seen["json"]["max_tokens"] == 8000

    for resp, msg in [
        (_Resp(429, {"error": {"message": "rate limited"}}), "HTTP 429"),
        (_Resp(200, {"choices": [{"message": {"content": ""}}]}), "빈 응답"),
        (_Resp(200, {"choices": [{"message": {"content": None}}]}), "빈 응답"),
        (_Resp(200, {"choices": []}), "빈 응답"),
        (_Resp(200, {"error": {"code": 502, "message": "upstream"}}), "오류 응답"),
        (_Resp(200, ValueError("not json")), "JSON"),
    ]:
        monkeypatch.setattr(ai.requests, "post", _fake_post(resp, {}))
        with pytest.raises(AIError, match=msg) as info:
            call_openrouter("m", [], "KEY123")
        assert "KEY123" not in str(info.value)


def test_existing_members_listed_in_their_own_team_are_ignored():
    teams, unassigned = hard_after_close()
    plan = find_assignment(teams, unassigned)
    listed = [{"student_no": m.student_no, "team": t} for t, ms in teams.items() for m in ms]
    text = json.dumps({"assignments": listed + [{"student_no": k, "team": v} for k, v in plan.items()]})
    r = run_assignment(teams, unassigned, call_model=lambda m: text, models=("a", "b", "c"), deadline_sec=2, **QUIET)
    assert r.source == "1차 모델 a" and r.plan == plan


def test_moving_an_existing_member_is_still_a_failure():
    teams, unassigned = hard_after_close()
    plan = find_assignment(teams, unassigned)
    moved = [{"student_no": "2026301", "team": 4}] + [{"student_no": k, "team": v} for k, v in plan.items()]
    r = run_assignment(teams, unassigned, call_model=lambda m: json.dumps({"assignments": moved}),
                       models=("a", "b", "c"), deadline_sec=2, **QUIET)
    assert r.source == "앱 자체 배정" and "이미 팀" in r.failures[0]
