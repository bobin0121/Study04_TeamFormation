# 생성: 2026-10-28 19:46 KST
import secrets
import threading

import pytest

import auth
import db
import rules
import service
from roster import parse_roster
from tests.conftest import TEST_SCHEMA
from tests.scenarios import FIXTURES, SCENARIOS


def _start(conn, name):
    sc = SCENARIOS[name]
    auth.ensure_admin(conn, secrets.token_hex(8))
    out = service.reset_roster(conn, "admin", parse_roster((FIXTURES / sc.csv_name).read_bytes()), sc.team_count)
    assert out.kind == "승인", out.text()
    return sc


def run_action(conn, a):
    if a.kind == "apply":
        return service.apply(conn, a.actor, a.target)
    if a.kind in ("yes", "no"):
        return service.vote(conn, a.actor, a.target, a.kind == "yes")
    if a.kind == "close":
        return service.close_recruitment(conn, a.actor)
    if a.kind == "assign_confirm":
        snap = service.load_snapshot(conn)
        plan = rules.find_assignment(snap.teams, snap.unassigned)
        assert plan is not None
        service.save_plan(conn, a.actor, plan, "앱 자체 배정")
        return service.confirm_plan(conn, a.actor)
    raise AssertionError(a.kind)


@pytest.mark.parametrize("name", ["쉬움", "중간", "어려움"])
def test_practice_scenario(conn, name):
    sc = _start(conn, name)
    for a in sc.actions:
        out = run_action(conn, a)
        assert out.kind == a.expect, f"{name} {a}: {out.text()}"
        assert out.text().startswith(a.expect + ": ")
        if a.kind == "close":
            names = {s.name for s in service.load_snapshot(conn).unassigned}
            assert set(a.expect_unassigned) <= names, names
    snap = service.load_snapshot(conn)
    assert snap.unassigned == [] and snap.confirmed
    assert all(not rules.team_errors(t, m) for t, m in snap.teams.items())


def test_hard_step8_reason_is_recheck(conn):
    sc = _start(conn, "어려움")
    last = None
    for a in sc.actions[:16]:          # 8단계의 마지막 찬성(학생5 -> 학생6)까지
        last = run_action(conn, a)
    assert last.text() == "거절: 승인 직전 검사에서 같은 주 역할의 팀원이 있음"


def test_hard_step11_reason_is_required_slot(conn):
    sc = _start(conn, "어려움")
    out = None
    for a in sc.actions:
        out = run_action(conn, a)
        if a.actor == "2026314":
            break
    assert out.text() == "막힘: " + rules.R_REQUIRED


def test_snapshot_shapes(conn):
    _start(conn, "어려움")
    service.apply(conn, "2026301", 1)
    service.apply(conn, "2026304", 1)
    snap = service.load_snapshot(conn)
    assert sorted(snap.teams) == [1, 2, 3, 4]
    assert [m.student_no for m in snap.teams[1]] == ["2026301"]
    assert snap.team_of("2026301") == 1 and snap.team_of("2026304") is None
    p = snap.pending_of("2026304")
    assert p.team_no == 1 and p.applicant.main_role == rules.WP and p.votes == {}
    assert snap.student("2026313").sub_roles == ("발표자", "프론트엔드 디자이너")
    assert len(snap.unassigned) == 15 and not snap.closed and not snap.confirmed and snap.plan is None


def test_student_cannot_use_admin_functions(conn):
    _start(conn, "쉬움")
    roster = parse_roster((FIXTURES / "쉬움.csv").read_bytes())
    for out in (service.reset_roster(conn, "2026101", roster, 3),
                service.close_recruitment(conn, "2026101"),
                service.confirm_plan(conn, "2026101")):
        assert out.text() == "막힘: 관리자만 할 수 있음"
    with pytest.raises(PermissionError):
        service.save_plan(conn, "2026101", {}, "x")
    assert not service.load_snapshot(conn).closed


def test_login_rules(conn):
    admin_pw = secrets.token_hex(8)
    auth.ensure_admin(conn, admin_pw)
    service.reset_roster(conn, "admin", parse_roster((FIXTURES / "쉬움.csv").read_bytes()), 3)
    assert auth.login(conn, "2026101", "1234") == {"student_no": "2026101", "name": "학생1(PL;RW)", "is_admin": False}
    assert auth.login(conn, "2026101", "12345") is None
    assert auth.login(conn, "9999999", "1234") is None
    assert auth.login(conn, "admin", admin_pw)["is_admin"] is True
    assert auth.login(conn, "admin", "1234") is None
    with conn.cursor() as cur:
        cur.execute("select password_hash from tf_students")
        hashes = [r["password_hash"] for r in cur.fetchall()]
    conn.rollback()
    assert hashes and all(h.startswith("$2") and "1234" not in h for h in hashes)


def test_admin_password_is_updated_on_restart(conn):
    auth.ensure_admin(conn, "first-" + secrets.token_hex(4))
    second = "second-" + secrets.token_hex(4)
    auth.ensure_admin(conn, second)
    assert auth.login(conn, "admin", second) is not None


def test_reset_keeps_admin_and_clears_everything(conn):
    sc = _start(conn, "어려움")
    for a in sc.actions[:12]:
        run_action(conn, a)
    service.close_recruitment(conn, "admin")
    out = service.reset_roster(conn, "admin", parse_roster((FIXTURES / "쉬움.csv").read_bytes()), 3)
    assert out.text() == "승인: 명단 8명과 팀 3개로 처음 상태를 만듦"
    snap = service.load_snapshot(conn)
    assert not snap.closed and not snap.confirmed and snap.plan is None and snap.pending == []
    assert sorted(snap.teams) == [1, 2, 3] and all(m == [] for m in snap.teams.values())
    assert len(snap.unassigned) == 8 and snap.student("2026301") is None
    with conn.cursor() as cur:
        cur.execute("select count(*) as n from tf_students where is_admin")
        assert cur.fetchone()["n"] == 1
        cur.execute("select count(*) as n from tf_votes")
        assert cur.fetchone()["n"] == 0
    conn.rollback()


def test_bad_team_count_is_blocked(conn):
    auth.ensure_admin(conn, secrets.token_hex(8))
    roster = parse_roster((FIXTURES / "쉬움.csv").read_bytes())
    assert service.reset_roster(conn, "admin", roster, 0).kind == "막힘"


def test_apply_to_unknown_team_is_blocked(conn):
    _start(conn, "쉬움")
    assert service.apply(conn, "2026101", 9).kind == "막힘"


def test_vote_twice_is_blocked(conn):
    _start(conn, "쉬움")
    service.apply(conn, "2026101", 1)
    service.apply(conn, "2026102", 1)
    service.apply(conn, "2026104", 1)
    assert service.vote(conn, "2026101", "2026104", True).kind == "승인"
    service.apply(conn, "2026107", 1)
    assert service.vote(conn, "2026101", "2026107", True).kind == "대기"
    assert service.vote(conn, "2026101", "2026107", False).text() == "막힘: 이미 투표함"


def test_non_member_cannot_vote(conn):
    _start(conn, "쉬움")
    service.apply(conn, "2026101", 1)
    service.apply(conn, "2026104", 1)
    assert service.vote(conn, "2026102", "2026104", True).text() == "막힘: 이 팀의 팀원만 투표할 수 있음"
    assert service.vote(conn, "2026101", "2026105", True).text() == "막힘: 대기 중인 지원이 없음"


def test_reapply_after_rejection(conn):
    _start(conn, "쉬움")
    service.apply(conn, "2026101", 1)
    service.apply(conn, "2026107", 1)
    assert service.vote(conn, "2026101", "2026107", False).kind == "거절"
    assert service.apply(conn, "2026107", 1).kind == "대기"      # 결과가 나온 뒤에는 다시 지원할 수 있음


def test_new_member_must_also_vote(conn):
    # 공고 2.4절: 지원한 뒤 다른 지원자가 먼저 승인되면 그 사람도 투표함
    _start(conn, "어려움")
    service.apply(conn, "2026302", 2)
    service.apply(conn, "2026305", 2)
    service.apply(conn, "2026313", 2)
    assert service.vote(conn, "2026302", "2026305", True).kind == "승인"
    assert service.vote(conn, "2026302", "2026313", True).kind == "대기"    # 학생5가 아직 투표하지 않음
    assert service.vote(conn, "2026305", "2026313", True).kind == "승인"


def test_close_twice_and_assign_states(conn):
    _start(conn, "쉬움")
    assert service.confirm_plan(conn, "admin").text() == "막힘: 모집을 먼저 마감해야 함"
    assert service.close_recruitment(conn, "admin").text() == "승인: 모집을 마감함"
    assert service.close_recruitment(conn, "admin").text() == "막힘: 이미 마감됨"
    assert service.confirm_plan(conn, "admin").text() == "막힘: 확정할 배정안이 없음"


def test_confirm_rejects_stale_plan(conn):
    sc = _start(conn, "어려움")
    for a in sc.actions:
        if a.kind == "assign_confirm":
            break
        run_action(conn, a)
    snap = service.load_snapshot(conn)
    plan = rules.find_assignment(snap.teams, snap.unassigned)
    bad = dict(plan)
    bad[next(iter(bad))] = 99
    service.save_plan(conn, "admin", bad, "x")
    assert service.confirm_plan(conn, "admin").kind == "막힘"
    service.save_plan(conn, "admin", plan, "앱 자체 배정")
    assert service.confirm_plan(conn, "admin").text() == "승인: 배정안을 확정함"
    assert service.confirm_plan(conn, "admin").text() == "막힘: 이미 확정함"


def test_two_students_apply_to_same_empty_team_at_once(conn, dsn):
    _start(conn, "쉬움")
    barrier = threading.Barrier(2)
    results = {}

    def go(no):
        c = db.connect(dsn, schema=TEST_SCHEMA)
        try:
            barrier.wait()
            results[no] = service.apply(c, no, 1).kind
        finally:
            c.close()

    threads = [threading.Thread(target=go, args=(no,)) for no in ("2026101", "2026104")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(results.values()) == ["대기", "승인"]
    assert len(service.load_snapshot(conn).teams[1]) == 1
