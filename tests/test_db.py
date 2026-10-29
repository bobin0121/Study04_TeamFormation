# 생성: 2026-10-28 19:40 KST
import threading

import psycopg2
import psycopg2.errors
import pytest

import config
import db


def _seed(conn):
    with conn.cursor() as cur:
        cur.execute("insert into tf_students (student_no, name, main_role, password_hash) values "
                    "('1', 'a', '기획자', 'h'), ('2', 'b', '테스터', 'h') returning id")
        ids = [r["id"] for r in cur.fetchall()]
        cur.execute("insert into tf_teams (id, name) values (1, '팀1')")
    conn.commit()
    return ids


def _violates(conn, error, sql, params=()):
    with pytest.raises(error):
        with conn.cursor() as cur:
            cur.execute(sql, params)
    conn.rollback()


def test_schema_constraints(conn):
    a, b = _seed(conn)
    with conn.cursor() as cur:
        cur.execute("insert into tf_members (team_id, slot_no, student_id) values (1, 1, %s)", (a,))
    conn.commit()
    # 같은 자리에 두 번: 먼저 도착한 학생만 기록(마지막 자리에 두 명이 동시에 들어감)
    _violates(conn, psycopg2.errors.UniqueViolation,
              "insert into tf_members (team_id, slot_no, student_id) values (1, 1, %s)", (b,))
    # 한 학생은 한 팀에만
    _violates(conn, psycopg2.errors.UniqueViolation,
              "insert into tf_members (team_id, slot_no, student_id) values (1, 2, %s)", (a,))
    # 다섯 번째 자리 없음
    _violates(conn, psycopg2.errors.CheckViolation,
              "insert into tf_members (team_id, slot_no, student_id) values (1, 5, %s)", (b,))
    # 대기 중인 지원은 학생당 1개
    with conn.cursor() as cur:
        cur.execute("insert into tf_applications (team_id, student_id, status) values (1, %s, '대기')", (b,))
    conn.commit()
    _violates(conn, psycopg2.errors.UniqueViolation,
              "insert into tf_applications (team_id, student_id, status) values (1, %s, '대기')", (b,))
    # 역할은 6개 가운데 하나
    _violates(conn, psycopg2.errors.CheckViolation,
              "insert into tf_students (student_no, name, main_role, password_hash) values ('3', 'c', '요리사', 'h')")
    _violates(conn, psycopg2.errors.CheckViolation,
              "insert into tf_student_sub_roles (student_id, role) values (%s, '요리사')", (a,))
    # 투표는 (지원, 투표자)마다 1번
    with conn.cursor() as cur:
        cur.execute("select id from tf_applications limit 1")
        app_id = cur.fetchone()["id"]
        cur.execute("insert into tf_votes (application_id, voter_id, vote) values (%s, %s, '찬성')", (app_id, a))
    conn.commit()
    _violates(conn, psycopg2.errors.UniqueViolation,
              "insert into tf_votes (application_id, voter_id, vote) values (%s, %s, '거부')", (app_id, a))


def test_dead_pool_recovers(dsn):
    with db.get_conn() as c:
        with c.cursor() as cur:
            cur.execute("select 1 as one")
    pool = db._pool()
    for c in list(pool._pool):      # 앱이 잠든 사이 연결이 모두 끊긴 상황을 흉내 냄
        c.close()
    with db.get_conn() as c:
        with c.cursor() as cur:
            cur.execute("select 1 as one")
            assert cur.fetchone()["one"] == 1


def test_pool_waits_instead_of_failing_under_load(dsn):
    errors = []

    def work():
        try:
            with db.get_conn() as c:
                with c.cursor() as cur:
                    cur.execute("select pg_sleep(0.3)")
        except Exception as e:      # PoolError가 나면 실패로 모은다
            errors.append(type(e).__name__)

    threads = [threading.Thread(target=work) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert errors == []


def test_bad_dsn_error_hides_connection_string():
    secret = "postgresql://user:SECRET_PW_123@nowhere.invalid:5432/postgres?bad"
    with pytest.raises(db.DBUnavailable) as info:
        db.open_pool(secret)
    assert "SECRET_PW_123" not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_get_secret_reports_presence_only(capsys):
    assert config.get_secret("NO_SUCH_KEY_FOR_TEST") is None
    assert capsys.readouterr().out == ""


def test_pool_uses_schema_from_env(dsn, monkeypatch):
    monkeypatch.setenv("TF_DB_SCHEMA", "tf_test")
    with db.get_conn() as c:
        with c.cursor() as cur:
            cur.execute("show search_path")
            assert cur.fetchone()["search_path"].strip('"') == "tf_test"
    monkeypatch.delenv("TF_DB_SCHEMA")
    with db.get_conn() as c:
        with c.cursor() as cur:
            cur.execute("show search_path")
            assert "tf_test" not in cur.fetchone()["search_path"]


def test_checkout_retries_a_failed_new_connection(dsn, monkeypatch):
    pool = db._pool()
    real = pool.getconn
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise psycopg2.OperationalError("잠깐 끊김")
        return real(*a, **k)

    monkeypatch.setattr(pool, "getconn", flaky)
    with db.get_conn() as c:
        with c.cursor() as cur:
            cur.execute("select 1 as one")
            assert cur.fetchone()["one"] == 1
    assert calls["n"] == 2
