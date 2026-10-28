# 생성: 2026-10-28 19:46 KST
"""로그인과 비밀번호 해시. 비밀번호는 bcrypt 해시로만 저장한다."""

import bcrypt

ADMIN_NO = "admin"
STUDENT_PASSWORD = "1234"
_ROUNDS = 10


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt(rounds=_ROUNDS)).decode("ascii")


def check_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:  # 72바이트가 넘는 입력이나 깨진 해시
        return False


def ensure_admin(conn, admin_password: str) -> None:
    """admin 계정이 없으면 만들고, 있으면 비밀번호가 달라졌을 때만 갱신한다."""
    if len(admin_password.encode("utf-8")) > 72:
        raise ValueError("ADMIN_PASSWORD는 72바이트 이하여야 함")
    with conn.cursor() as cur:
        cur.execute("select id, password_hash from tf_students where student_no = %s", (ADMIN_NO,))
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "insert into tf_students (student_no, name, main_role, password_hash, is_admin) "
                "values (%s, '관리자', null, %s, true) on conflict (student_no) do nothing",
                (ADMIN_NO, hash_password(admin_password)),
            )
        elif not check_password(admin_password, row["password_hash"]):
            cur.execute("update tf_students set password_hash = %s, is_admin = true where id = %s",
                        (hash_password(admin_password), row["id"]))
    conn.commit()


def login(conn, student_no: str, password: str) -> dict | None:
    """성공하면 {"student_no", "name", "is_admin"}. 학번이 없든 비밀번호가 틀리든 똑같이 None."""
    with conn.cursor() as cur:
        cur.execute("select student_no, name, password_hash, is_admin from tf_students where student_no = %s",
                    (student_no.strip(),))
        row = cur.fetchone()
    conn.commit()
    if row is None or not check_password(password, row["password_hash"]):
        return None
    return {"student_no": row["student_no"], "name": row["name"], "is_admin": bool(row["is_admin"])}
