# 생성: 2026-10-28 19:40 KST
"""DB 테스트 준비. 운영 데이터를 건드리지 않도록 같은 DB의 시험용 스키마 tf_test를 쓴다.
DATABASE_URL이 없으면 DB 테스트는 건너뛴다."""

import pytest

import config
import db

TEST_SCHEMA = "tf_test"
TABLES = ["tf_votes", "tf_applications", "tf_members", "tf_teams",
          "tf_student_sub_roles", "tf_students", "tf_settings", "tf_ai_logs"]


@pytest.fixture(scope="session")
def dsn():
    value = config.get_secret("DATABASE_URL")
    if not value:
        pytest.skip("DATABASE_URL 없음")
    return value


@pytest.fixture(scope="session")
def _session_conn(dsn):
    conn = db.connect(dsn, schema=TEST_SCHEMA)
    db.apply_schema(conn)
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def conn(_session_conn):
    c = _session_conn
    c.rollback()
    with c.cursor() as cur:
        cur.execute(f"truncate {', '.join(TABLES)} restart identity cascade")
    c.commit()
    yield c
    c.rollback()
