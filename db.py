# 생성: 2026-10-28 19:40 KST
"""DB 연결. 연결 풀을 한 번만 만들어 다시 쓴다(공고 4.2절).

연결 문자열에는 DB 비밀번호가 들어 있으므로, 연결 오류는 내용을 버리고 DBUnavailable로 바꾼다.
"""

import os
import re
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import psycopg2.extras
import psycopg2.pool
import streamlit as st

import config

POOL_SIZE = 8
SCHEMA_FILE = Path(__file__).parent / "schema.sql"
def _connect_options() -> dict:
    options = dict(
        cursor_factory=psycopg2.extras.RealDictCursor,
        connect_timeout=10,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=3,
    )
    if sys.platform.startswith("linux"):
        # 앱이 잠든 사이 끊긴 연결에 질의를 보내면 TCP 기본값 때문에 10분 넘게 멈춘다.
        # 응답 없는 전송을 8초 만에 끊는다(Streamlit Cloud는 리눅스. 교수 예제 recipe4fridge와 같은 값).
        options["tcp_user_timeout"] = 8000
    return options


class DBUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("DB에 연결할 수 없음.")


def connect(dsn: str, schema: str | None = None):
    """연결 하나(테스트와 도구용). schema를 주면 그 스키마를 만들고 search_path로 쓴다."""
    try:
        conn = psycopg2.connect(dsn, **_connect_options())
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
        # minconn을 maxconn과 같게 둔다. psycopg2 풀은 쉬는 연결을 minconn개만 남기고 돌려받을 때 닫아 버려서,
        # minconn이 작으면 화면을 다시 그릴 때마다 새 연결(TLS 포함)을 맺는다. 새 연결을 맺는 동안 풀 전체가
        # 잠기므로 학생이 많으면 단추 처리가 줄을 서서 사라진 것처럼 보였다(검증에서 9번째 학생부터 발생).
        return psycopg2.pool.ThreadedConnectionPool(POOL_SIZE, POOL_SIZE, dsn, **_connect_options())
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
    """연결을 꺼낼 때마다 질의 제한 시간(15초)을 건다. 응답 없는 질의가 화면을 붙잡고 있지 않게 하기 위함이다.
    테스트에서만 TF_DB_SCHEMA(예: tf_test)를 켜서 앱이 시험용 스키마를 쓰게 한다. 비밀 값이 아니다."""
    schema = os.environ.get("TF_DB_SCHEMA", "")
    if not schema:
        return "reset search_path; set statement_timeout = '15s'; "
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", schema):
        raise ValueError("TF_DB_SCHEMA는 영문 소문자, 숫자, 밑줄만 쓸 수 있음")
    return f"set search_path to \"{schema}\"; set statement_timeout = '15s'; "


def _checkout():
    """살아 있는 연결을 꺼낸다. 앱이 잠들었다 깨면 쉬고 있던 연결이 모두 죽어 있으므로,
    죽은 연결은 하나씩 버리고 다시 꺼낸다(쉬는 연결이 없으면 풀이 새로 만든다).
    풀 전체를 닫지 않는 것은 다른 사용자가 쓰는 중인 연결을 끊지 않기 위해서다."""
    pool = _pool()
    retried = False
    for _ in range(POOL_SIZE + 2):
        try:
            conn = pool.getconn()
        except psycopg2.Error:
            if retried:  # 새 연결을 두 번 연달아 못 만들면 DB가 정말 안 되는 것으로 본다
                raise DBUnavailable() from None
            retried = True
            time.sleep(0.5)  # 네트워크가 잠깐 끊긴 경우를 위해 한 번 더 해 본다
            continue
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
        except BaseException as e:
            try:
                conn.rollback()
            except psycopg2.Error:
                pass
            if isinstance(e, (psycopg2.OperationalError, psycopg2.InterfaceError)):
                raise DBUnavailable() from None  # 처리 도중 연결이 끊김. 메시지는 버린다.
            raise
        finally:
            pool.putconn(conn, close=bool(conn.closed))
