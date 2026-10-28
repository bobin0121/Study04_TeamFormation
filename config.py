# 생성: 2026-10-28 19:40 KST
"""키 읽기. 내 컴퓨터에서는 .env, 배포한 앱에서는 Streamlit Secrets에서 읽는다.
값은 어디에도 출력하지 않는다."""

import os

from dotenv import load_dotenv

load_dotenv()


def get_secret(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st
        value = st.secrets.get(name)
    except Exception:  # secrets.toml이 없거나 Streamlit 밖에서 실행됨
        return None
    return str(value) if value else None
