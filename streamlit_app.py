# 생성: 2026-10-29 21:00 KST
"""팀 편성 웹 앱 화면(PRD 7장). 화면 요소의 key는 공고 2.7절 표와 같아야 한다."""

import logging

import streamlit as st

import ai
import auth
import config
import db
import service
from roster import RosterError, parse_roster

st.set_page_config(page_title="팀 편성", page_icon="👥")

REFRESH_SEC = 2  # 다른 사람의 변경을 2초마다 다시 그림(공고: 5초 이하)


@st.cache_resource(show_spinner=False)
def _bootstrap() -> bool:
    """앱이 시작할 때 한 번: 테이블을 만들고 관리자 계정을 만들거나 비밀번호를 갱신한다."""
    with db.get_conn() as conn:
        db.apply_schema(conn)
        conn.commit()
        auth.ensure_admin(conn, config.get_secret("ADMIN_PASSWORD"))
    return True


def _snapshot() -> service.Snapshot:
    with db.get_conn() as conn:
        return service.load_snapshot(conn)


def _set_result(text: str) -> None:
    st.session_state["result"] = text


def _show_result(box) -> None:
    """result 상자에 마지막 결과 안내를 그린다.

    상자는 화면 위쪽에 먼저 만들고, 내용은 화면을 다 그린 뒤 맨 마지막에 넣는다. 그래야 안내가 바뀌어
    보이는 순간에는 그 아래 단추(비활성 등)도 이미 바뀌어 있다. 그 전까지는 예전 안내가 그대로 보인다.
    """
    text = st.session_state.get("result")
    with box.container():
        if not text:
            st.caption("안내 없음")
        elif text.startswith("승인"):
            st.success(text)
        elif text.startswith("대기"):
            st.info(text)
        else:
            st.error(text)


def _safe_action(fn):
    """단추 처리가 실패하면, 처리하지 못했다는 안내를 result에 남긴다.
    그래야 앞 단계의 안내가 남아 잘못 읽히지 않는다. 오류 내용은 화면에 내지 않는다."""
    def wrapped(*args):
        try:
            fn(*args)
        except db.DBUnavailable as e:
            _set_result(f"막힘: {e}")
        except Exception as e:
            logging.getLogger(__name__).warning("단추 처리 실패: %s", type(e).__name__)
            _set_result("막힘: 처리하지 못함. 다시 시도해 주세요.")
    return wrapped


def _db_down(e: Exception) -> None:
    st.error(f"{e} 잠시 뒤 다시 시도해 주세요.")


def _logout() -> None:
    for k in ("user", "result", "assign_lines"):
        st.session_state.pop(k, None)


def _whoami(user: dict) -> None:
    with st.container(key="whoami"):
        cols = st.columns([4, 1])
        label = "관리자" if user["is_admin"] else user["name"]
        cols[0].markdown(f"**{label}** ({user['student_no']}) 로그인함")
        cols[1].button("로그아웃", key="logout", on_click=_logout)


def _member_line(s) -> str:
    subs = ", ".join(s.sub_roles) if s.sub_roles else "없음"
    return f"- {s.name}: 주 역할 {s.main_role}, 보조 역할 {subs}"


def _team_box(snap: service.Snapshot, t: int, my_team: int | None):
    box = st.container(key=f"team_{t}", border=True)
    members = snap.teams[t]
    mine = " (내 팀)" if t == my_team else ""
    box.markdown(f"**팀{t}**{mine} {len(members)}/4명")
    box.markdown("\n".join(_member_line(m) for m in members) if members else "팀원 없음")
    return box


# ---------------- 로그인 ----------------

def login_view() -> None:
    st.title("팀 편성")
    with st.form("login_form"):
        no = st.text_input("학번", key="login_student_no")
        pw = st.text_input("비밀번호", type="password", key="login_password")
        submitted = st.form_submit_button("로그인", key="login_submit")
    if submitted:
        with db.get_conn() as conn:
            user = auth.login(conn, no, pw)
        if user:
            st.session_state["user"] = user
            st.session_state.pop("result", None)
            st.rerun()
        st.error("학번이나 비밀번호가 맞지 않음.")


# ---------------- 학생 화면 ----------------

@_safe_action
def _do_apply(student_no: str, team_no: int) -> None:
    with db.get_conn() as conn:
        _set_result(service.apply(conn, student_no, team_no).text())


@_safe_action
def _do_vote(voter_no: str, applicant_no: str, yes: bool) -> None:
    with db.get_conn() as conn:
        _set_result(service.vote(conn, voter_no, applicant_no, yes).text())


@st.fragment(run_every=REFRESH_SEC)
def student_board(user: dict) -> None:
    result_box = st.container(key="result")
    try:
        _student_body(user["student_no"])
    finally:
        _show_result(result_box)


def _student_body(me: str) -> None:
    try:
        snap = _snapshot()
    except db.DBUnavailable as e:
        _db_down(e)
        return
    my_team = snap.team_of(me)
    my_pending = snap.pending_of(me)

    if snap.confirmed:
        status = "팀 구성이 확정됨"
    elif my_team:
        status = f"내 팀: 팀{my_team}"
    elif my_pending:
        status = f"팀{my_pending.team_no} 지원 결과를 기다리는 중"
    else:
        status = "아직 팀이 없음"
    if snap.closed:
        status += ". 모집이 마감됨"
    st.markdown(f"**{status}**")

    # 이미 팀이 있음, 결과를 기다리는 지원이 있음, 모집 마감이면 지원 단추를 모두 비활성화한다(공고 2.8절).
    cannot_apply = bool(my_team or my_pending or snap.closed)
    st.subheader("팀 목록")
    cols = st.columns(2)
    for i, t in enumerate(sorted(snap.teams)):
        with cols[i % 2]:
            box = _team_box(snap, t, my_team)
            box.button(f"팀{t}에 지원", key=f"apply_{t}", disabled=cannot_apply,
                       on_click=_do_apply, args=(me, t))

    if my_team:
        st.subheader("내 팀에 들어온 지원")
        incoming = [p for p in snap.pending if p.team_no == my_team]
        if not incoming:
            st.caption("대기 중인 지원 없음")
        for p in incoming:
            a = p.applicant
            yes = sum(v == "찬성" for v in p.votes.values())
            with st.container(border=True):
                st.markdown(_member_line(a)[2:] + f" (찬성 {yes}/{len(snap.teams[my_team])}명)")
                if me in p.votes:
                    st.markdown(f"내 투표: {p.votes[me]}")
                elif not snap.closed:
                    c1, c2 = st.columns(2)
                    c1.button("찬성", key=f"vote_yes_{a.student_no}", on_click=_do_vote,
                              args=(me, a.student_no, True))
                    c2.button("거부", key=f"vote_no_{a.student_no}", on_click=_do_vote,
                              args=(me, a.student_no, False))


# ---------------- 관리자 화면 ----------------

def _require_admin() -> str | None:
    user = st.session_state.get("user")
    return user["student_no"] if user and user["is_admin"] else None


@_safe_action
def _do_start() -> None:
    actor = _require_admin()
    if not actor:
        return
    file = st.session_state.get("admin_roster_file")
    if file is None:
        _set_result("막힘: 명단 CSV 파일을 골라야 함")
        return
    try:
        students = parse_roster(file.getvalue())
    except RosterError as e:
        _set_result(f"막힘: {e}")
        return
    with db.get_conn() as conn:
        out = service.reset_roster(conn, actor, students, int(st.session_state.get("admin_team_count") or 0))
    st.session_state.pop("assign_lines", None)
    _set_result(out.text())


@_safe_action
def _do_close() -> None:
    actor = _require_admin()
    if actor:
        with db.get_conn() as conn:
            _set_result(service.close_recruitment(conn, actor).text())


@_safe_action
def _do_confirm() -> None:
    actor = _require_admin()
    if actor:
        with db.get_conn() as conn:
            _set_result(service.confirm_plan(conn, actor).text())


def _run_assign(actor: str, live) -> None:
    """AI 배정. 기다리는 동안 live(assign_status 안의 자리)에 몇 차 모델을 몇 초째 기다리는지와 실패 줄을 보여 준다."""
    snap = _snapshot()
    if not snap.closed:
        _set_result("막힘: 모집을 먼저 마감해야 함")
        return
    if snap.confirmed:
        _set_result("막힘: 이미 확정함")
        return
    key = config.get_secret("OPENROUTER_API_KEY") or ""
    messages = ai.build_messages(snap.teams, snap.unassigned)
    area = live.container()
    progress = area.empty()
    lines: list[str] = []

    def on_progress(text: str) -> None:
        progress.info(text)

    def log(attempt, model, outcome, detail, elapsed) -> None:
        with db.get_conn() as conn:
            service.log_ai(conn, attempt, model, outcome, detail, elapsed)
        if outcome == "실패":
            lines.append(f"{attempt}차 모델({model}) 실패: {detail}")
            area.warning(lines[-1])

    result = ai.run_assignment(
        snap.teams, snap.unassigned,
        call_model=lambda model: ai.call_openrouter(model, messages, key),
        on_progress=on_progress, log=log,
    )
    live.empty()
    if result.reasons:
        st.session_state["assign_lines"] = ["규칙을 지키는 배정이 없음", *result.reasons]
        _set_result("막힘: 규칙을 지키는 배정이 없음")
        return
    with db.get_conn() as conn:
        service.save_plan(conn, actor, result.plan, result.source)
    st.session_state["assign_lines"] = [*result.failures, f"배정안을 만든 곳: {result.source}"]
    _set_result(f"승인: 배정안을 만듦({result.source})")


@st.fragment(run_every=REFRESH_SEC)
def admin_board() -> None:
    try:
        snap = _snapshot()
    except db.DBUnavailable as e:
        _db_down(e)
        return
    state = "확정됨" if snap.confirmed else "마감됨" if snap.closed else "모집 중"
    st.markdown(f"**상태: {state}**")
    cols = st.columns(2)
    for i, t in enumerate(sorted(snap.teams)):
        with cols[i % 2]:
            _team_box(snap, t, None)
    st.subheader("팀이 없는 학생")
    with st.container(key="unassigned", border=True):
        st.markdown("\n".join(_member_line(s) for s in snap.unassigned) if snap.unassigned else "없음")


def admin_view(user: dict) -> None:
    # 관리자 화면은 단추를 누를 때만 다시 그리므로, 그리는 동안 result를 비워 두었다가 마지막에 채운다.
    result_slot = st.container(key="result").empty()
    try:
        _admin_body(user, result_slot)
    finally:
        # 아래에서 DB 오류가 나도 방금 누른 단추의 결과는 반드시 보이게 한다.
        _show_result(result_slot)


def _admin_body(user: dict, result_slot) -> None:

    st.subheader("1. 명단으로 처음 상태 만들기")
    st.file_uploader("명단 CSV", type=["csv"], key="admin_roster_file")
    st.number_input("팀 수", min_value=1, max_value=20, value=3, step=1, key="admin_team_count")
    st.button("명단으로 처음 상태 만들기", key="admin_start", on_click=_do_start)

    st.subheader("2. 모집 마감")
    st.button("모집 마감", key="admin_close", on_click=_do_close)

    st.subheader("팀 현황")
    admin_board()

    st.subheader("3. AI 배정")
    clicked = st.button("AI 배정", key="admin_assign")
    status_box = st.container(key="assign_status", border=True)
    live = status_box.empty()
    if clicked:
        st.session_state.pop("assign_lines", None)
        try:
            # AI를 기다리는 동안(최대 약 6분) 앞 단계의 안내가 이번 결과로 읽히지 않게 한다.
            # 이 안내는 승인, 대기, 거절, 막힘 가운데 어느 것으로도 시작하지 않는다.
            result_slot.info("AI 배정 중: 결과를 기다리는 중")
            _run_assign(user["student_no"], live)
        except db.DBUnavailable as e:
            live.empty()
            _set_result(f"막힘: {e}")
    lines = st.session_state.get("assign_lines")
    if lines:
        for line in lines:
            status_box.markdown(line)
    else:
        status_box.caption("AI 배정 전")

    with st.expander("AI 호출 기록(최근 20건, 한국 시각)", expanded=bool(lines)):
        try:
            with db.get_conn() as conn:
                logs = service.recent_ai_logs(conn, 20)
        except db.DBUnavailable as e:
            _db_down(e)
            logs = []
        if not logs:
            st.caption("기록 없음")
        for r in logs:
            detail = f"({r['detail']}, {r['elapsed_sec']}초)" if r["detail"] else f"({r['elapsed_sec']}초)"
            st.markdown(f"- {r['at']} {r['attempt']}차 {r['model']}: {r['outcome']}{detail}")

    st.subheader("4. 배정안 확인과 확정")
    try:
        snap = _snapshot()
    except db.DBUnavailable as e:
        _db_down(e)
        snap = None
    if snap is None:
        pass
    elif snap.plan and not snap.confirmed:
        rows = []
        for no, t in sorted(snap.plan["assignments"].items(), key=lambda p: (p[1], p[0])):
            s = snap.student(no)
            if s:
                rows.append({"이름": s.name, "주 역할": s.main_role, "보조 역할": ", ".join(s.sub_roles) or "없음",
                             "배정된 팀": f"팀{t}", "만든 곳": snap.plan["source"]})
        st.table(rows)
    elif snap.confirmed:
        st.caption("배정안을 확정함")
    else:
        st.caption("배정안 없음")
    st.button("배정안 확정", key="admin_confirm", on_click=_do_confirm)


# ---------------- 시작 ----------------

def main() -> None:
    missing = [n for n in ("DATABASE_URL", "ADMIN_PASSWORD") if not config.get_secret(n)]
    if missing:
        st.error("설정이 없음: " + ", ".join(missing))
        st.stop()
    try:
        _bootstrap()
        user = st.session_state.get("user")
        if not user:
            login_view()
            return
        if not user["is_admin"]:
            s = _snapshot().student(user["student_no"])
            if s is None or s.name != user["name"]:  # 명단을 다시 올려 이 학생이 사라짐
                _logout()
                st.rerun()
        _whoami(user)
        if user["is_admin"]:
            admin_view(user)
        else:
            student_board(user)
    except db.DBUnavailable as e:
        _db_down(e)


main()
