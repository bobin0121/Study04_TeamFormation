# 생성: 2026-10-28 19:40 KST
"""DB 연결. 연결 풀을 한 번만 만들어 다시 쓴다(공고 4.2절).

연결 문자열에는 DB 비밀번호가 들어 있으므로, 연결 오류는 내용을 버리고 DBUnavailable로 바꾼다.
"""

import os
import re
import threading
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import psycopg2.extras
import psycopg2.pool
import streamlit as st

import config

POOL_SIZE = 8
SCHEMA_FILE = Path(__file__).parent / "schema.sql"
_CONNECT_OPTIONS = dict(
    cursor_factory=psycopg2.extras.RealDictCursor,
    connect_timeout=10,
    keepalives=1,
    keepalives_idle=30,
    keepalives_interval=10,
    keepalives_count=3,
)


class DBUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("DB에 연결할 수 없음.")


def connect(dsn: str, schema: str | None = None):
    """연결 하나(테스트와 도구용). schema를 주면 그 스키마를 만들고 search_path로 쓴다."""
    try:
        conn = psycopg2.connect(dsn, **_CONNECT_OPTIONS)
    except psycopg2.Error:
        raise DBUnavailable() from None
    if schema:
        with conn.cursor() as cur:
            cur.execute(f'create schema if not exists "{schema}"')
            cur.execute(f'set search_path to "{schema}"')
        conn.commit()
    return conn


def apply_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA_FILE.read_text(encoding="utf-8"))


def open_pool(dsn: str) -> psycopg2.pool.ThreadedConnectionPool:
    try:
        return psycopg2.pool.ThreadedConnectionPool(1, POOL_SIZE, dsn, **_CONNECT_OPTIONS)
    except psycopg2.Error:
        raise DBUnavailable() from None


@st.cache_resource(show_spinner=False)
def _pool() -> psycopg2.pool.ThreadedConnectionPool:
    dsn = config.get_secret("DATABASE_URL")
    if not dsn:
        raise DBUnavailable()
    return open_pool(dsn)


# 풀의 getconn()은 연결이 모두 쓰이는 중이면 기다리지 않고 PoolError를 던진다.
# 학생 브라우저 여러 개가 동시에 화면을 다시 그려도 오류가 나지 않게, 풀 크기만큼의 세마포어로 기다리게 한다.
_slots = threading.BoundedSemaphore(POOL_SIZE)


def _search_path_sql() -> str:
    """테스트에서만 TF_DB_SCHEMA(예: tf_test)를 켜서 앱이 시험용 스키마를 쓰게 한다. 비밀 값이 아니다."""
    schema = os.environ.get("TF_DB_SCHEMA", "")
    if not schema:
        return "reset search_path; "
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", schema):
        raise ValueError("TF_DB_SCHEMA는 영문 소문자, 숫자, 밑줄만 쓸 수 있음")
    return f'set search_path to "{schema}"; '


def _checkout():
    """살아 있는 연결을 꺼낸다. 앱이 잠들었다 깨면 쉬고 있던 연결이 모두 죽어 있으므로,
    죽은 연결은 하나씩 버리고 다시 꺼낸다(쉬는 연결이 없으면 풀이 새로 만든다).
    풀 전체를 닫지 않는 것은 다른 사용자가 쓰는 중인 연결을 끊지 않기 위해서다."""
    pool = _pool()
    for _ in range(POOL_SIZE + 1):
        try:
            conn = pool.getconn()
        except psycopg2.Error:
            raise DBUnavailable() from None
        try:
            with conn.cursor() as cur:
                cur.execute(_search_path_sql() + "select 1")
            conn.commit()  # set search_path가 rollback으로 되돌아가지 않게 commit한다
            return pool, conn
        except psycopg2.Error:
            pool.putconn(conn, close=True)
    raise DBUnavailable()


@contextmanager
def get_conn():
    """앱용 연결. 블록이 끝나면 commit, 예외면 rollback하고 풀에 돌려준다."""
    with _slots:
        pool, conn = _checkout()
        try:
            yield conn
            conn.commit()
        except BaseException:
            try:
                conn.rollback()
            except psycopg2.Error:
                pass
            raise
        finally:
            pool.putconn(conn, close=bool(conn.closed))
