# 생성: 2026-10-29 21:00 KST
"""화면 테스트(Streamlit AppTest). 앱은 시험용 스키마 tf_test를 쓴다."""

import secrets
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import ai
import auth
import service
from roster import parse_roster
from tests.scenarios import FIXTURES

APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


@pytest.fixture
def admin_pw(conn, dsn, monkeypatch):
    pw = secrets.token_hex(8)
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("TF_DB_SCHEMA", "tf_test")
    monkeypatch.setenv("ADMIN_PASSWORD", pw)
    st.cache_resource.clear()
    auth.ensure_admin(conn, pw)
    service.reset_roster(conn, "admin", parse_roster((FIXTURES / "쉬움.csv").read_bytes()), 3)
    yield pw
    st.cache_resource.clear()


def _app():
    return AppTest.from_file(APP, default_timeout=60)


def _login(no, pw):
    at = _app().run()
    at.text_input(key="login_student_no").input(no)
    at.text_input(key="login_password").input(pw)
    at.button(key="login_submit").click().run()
    assert not at.exception, at.exception
    return at


def _texts(at) -> str:
    parts = []
    for kind in ("markdown", "caption", "success", "info", "error", "warning"):
        parts += [str(e.value) for e in getattr(at, kind)]
    return "\n".join(parts)


def _has_key(getter, key) -> bool:
    try:
        getter(key=key)
        return True
    except KeyError:
        return False


def test_login_screen_keys(admin_pw):
    at = _app().run()
    assert not at.exception
    at.text_input(key="login_student_no")
    at.text_input(key="login_password")
    at.button(key="login_submit")


def test_wrong_password_stays_out(admin_pw):
    at = _login("2026101", "9999")
    assert "user" not in at.session_state
    assert "학번이나 비밀번호가 맞지 않음." in _texts(at)
    at = _login("admin", "1234")
    assert "user" not in at.session_state


def test_admin_keys_present(admin_pw):
    at = _login("admin", admin_pw)
    assert at.session_state["user"]["is_admin"]
    for key in ("admin_start", "admin_close", "admin_assign", "admin_confirm"):
        at.button(key=key)
    at.number_input(key="admin_team_count")
    assert "**관리자** (admin) 로그인함" in _texts(at)


def test_student_cannot_see_admin_controls(admin_pw):
    at = _login("2026101", "1234")
    assert not _has_key(at.button, "admin_start")
    assert not _has_key(at.button, "admin_close")
    assert "**학생1(PL;RW)** (2026101) 로그인함" in _texts(at)


def test_admin_start_requires_file(admin_pw):
    at = _login("admin", admin_pw)
    at.button(key="admin_start").click().run()
    assert at.session_state["result"] == "막힘: 명단 CSV 파일을 골라야 함"


def test_student_apply_then_buttons_disabled(admin_pw):
    at = _login("2026101", "1234")
    assert not at.button(key="apply_1").disabled
    at.button(key="apply_1").click().run()
    assert at.session_state["result"] == "승인: 팀1에 들어감"
    assert all(at.button(key=f"apply_{t}").disabled for t in (1, 2, 3))
    assert "내 팀: 팀1" in _texts(at)


def test_pending_disables_apply_and_blocked_reason_shows(admin_pw, conn):
    service.apply(conn, "2026101", 1)
    at = _login("2026102", "1234")
    at.button(key="apply_1").click().run()
    assert at.session_state["result"] == "막힘: 같은 주 역할의 팀원이 있음"
    assert not at.button(key="apply_2").disabled
    at = _login("2026104", "1234")
    at.button(key="apply_1").click().run()
    assert at.session_state["result"] == "대기: 팀원의 투표를 기다림"
    assert all(at.button(key=f"apply_{t}").disabled for t in (1, 2, 3))


def test_vote_buttons_and_my_vote(admin_pw, conn):
    service.apply(conn, "2026101", 1)
    service.apply(conn, "2026104", 1)
    at = _login("2026101", "1234")
    at.button(key="vote_no_2026104")
    at.button(key="vote_yes_2026104").click().run()
    assert at.session_state["result"] == "승인: 팀1에 들어감"
    service.apply(conn, "2026107", 1)
    at.run()
    at.button(key="vote_yes_2026107").click().run()
    assert at.session_state["result"] == "대기: 다른 팀원의 투표를 기다림"
    assert not _has_key(at.button, "vote_yes_2026107")
    assert "내 투표: 찬성" in _texts(at)


def test_admin_flow_with_ai_failures_uses_app_assignment(admin_pw, conn, monkeypatch):
    for no, t in [("2026101", 1), ("2026102", 2), ("2026103", 3)]:
        service.apply(conn, no, t)

    def failing(model, messages, key):
        raise ai.AIError("HTTP 429")

    monkeypatch.setattr(ai, "call_openrouter", failing)
    at = _login("admin", admin_pw)
    at.button(key="admin_assign").click().run()
    assert at.session_state["result"] == "막힘: 모집을 먼저 마감해야 함"
    at.button(key="admin_close").click().run()
    assert at.session_state["result"] == "승인: 모집을 마감함"
    at.button(key="admin_assign").click().run()
    assert not at.exception, at.exception
    assert at.session_state["result"] == "승인: 배정안을 만듦(앱 자체 배정)"
    lines = at.session_state["assign_lines"]
    assert [ln.split(" 실패")[0][:5] for ln in lines[:3]] == ["1차 모델", "2차 모델", "3차 모델"]
    assert lines[-1] == "배정안을 만든 곳: 앱 자체 배정"
    at.button(key="admin_confirm").click().run()
    assert at.session_state["result"] == "승인: 배정안을 확정함"
    snap = service.load_snapshot(conn)
    assert snap.confirmed and snap.unassigned == []


def test_infeasible_assignment_shows_reason_without_ai(admin_pw, conn, monkeypatch):
    csv = ("student_no,name,main_role,sub_roles\n1,가,기획자,\n2,나,테스터,\n3,다,발표자,\n4,라,보고서 작성자,\n")
    service.reset_roster(conn, "admin", parse_roster(csv.encode()), 2)

    def must_not_call(model, messages, key):
        raise AssertionError("AI를 부르면 안 됨")

    monkeypatch.setattr(ai, "call_openrouter", must_not_call)
    at = _login("admin", admin_pw)
    at.button(key="admin_close").click().run()
    at.button(key="admin_assign").click().run()
    assert not at.exception, at.exception
    assert at.session_state["result"] == "막힘: 규칙을 지키는 배정이 없음"
    lines = at.session_state["assign_lines"]
    assert lines[0] == "규칙을 지키는 배정이 없음"
    assert any("웹 프로그래머를 맡을 학생이 없음" in ln for ln in lines[1:])


def test_stale_session_logs_out(admin_pw, conn):
    at = _login("2026101", "1234")
    assert "user" in at.session_state
    service.reset_roster(conn, "admin", parse_roster((FIXTURES / "어려움.csv").read_bytes()), 4)
    at.run()
    assert not at.exception, at.exception
    assert "user" not in at.session_state
    at.text_input(key="login_student_no")


def test_result_still_shown_when_board_cannot_reach_db(admin_pw, monkeypatch):
    # 단추 처리는 됐는데 화면을 다시 그리다 DB 연결이 잠깐 끊겨도, result에는 그 단추의 결과가 보여야 함
    at = _login("admin", admin_pw)
    import db as db_module

    def down(conn):
        raise db_module.DBUnavailable()

    monkeypatch.setattr(service, "load_snapshot", down)
    at.button(key="admin_close").click().run()
    assert not at.exception, at.exception
    assert any(str(e.value) == "승인: 모집을 마감함" for e in at.success)
    assert "DB에 연결할 수 없음." in _texts(at)


def test_action_reports_block_when_db_is_down(admin_pw, monkeypatch):
    at = _login("2026101", "1234")
    import db as db_module

    def down(*a, **k):
        raise db_module.DBUnavailable()

    monkeypatch.setattr(service, "apply", down)
    at.button(key="apply_1").click().run()
    assert not at.exception, at.exception
    assert at.session_state["result"] == "막힘: DB에 연결할 수 없음."


def test_ai_log_is_visible_to_admin(admin_pw, conn, monkeypatch):
    # 공고 4.3절: AI 실패 처리(120초 제한, 2차와 3차로 넘어감, 앱 자체 배정)를 화면 기록으로 확인할 수 있게 함
    for no, t in [("2026101", 1), ("2026102", 2), ("2026103", 3)]:
        service.apply(conn, no, t)

    def failing(model, messages, key):
        raise ai.AIError("HTTP 429")

    monkeypatch.setattr(ai, "call_openrouter", failing)
    at = _login("admin", admin_pw)
    at.button(key="admin_close").click().run()
    at.button(key="admin_assign").click().run()
    text = _texts(at)
    for i, model in enumerate(ai.MODELS, start=1):
        assert f"{i}차 {model}: 실패(HTTP 429" in text


def test_unexpected_error_in_action_still_reports_block(admin_pw, monkeypatch):
    at = _login("2026101", "1234")

    def broken(*a, **k):
        raise RuntimeError("예상하지 못한 오류 postgresql://secret")

    monkeypatch.setattr(service, "apply", broken)
    at.button(key="apply_1").click().run()
    assert not at.exception, at.exception
    assert at.session_state["result"] == "막힘: 처리하지 못함. 다시 시도해 주세요."
    assert "secret" not in _texts(at)
