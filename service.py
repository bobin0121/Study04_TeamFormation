# 생성: 2026-10-28 19:46 KST
"""지원, 투표, 마감, 명단 올리기, 배정안 확정(PRD 4장). 판정은 rules.py에 맡기고,
여기서는 DB 트랜잭션 안에서 상태를 읽고 결과를 쓴다. 함수마다 끝에서 commit한다.

같은 팀에 대한 처리는 팀 행을 잠가(select ... for update) 차례로 한다. 마감과 확정은 모든 팀을 잠근다.
"""

import json
from dataclasses import dataclass, field

import psycopg2
import psycopg2.errors
from psycopg2.extras import execute_values

import auth
import rules
from rules import Student, Teams


@dataclass(frozen=True)
class Outcome:
    kind: str  # "승인" | "대기" | "거절" | "막힘"
    message: str

    def text(self) -> str:
        return f"{self.kind}: {self.message}"


@dataclass(frozen=True)
class Pending:
    app_id: int
    applicant: Student
    team_no: int
    votes: dict[str, str]


@dataclass
class Snapshot:
    closed: bool
    confirmed: bool
    teams: Teams
    unassigned: list[Student]
    pending: list[Pending]
    plan: dict | None
    _students: dict[str, Student] = field(default_factory=dict)
    _ids: dict[str, int] = field(default_factory=dict)

    def student(self, no: str) -> Student | None:
        return self._students.get(no)

    def team_of(self, no: str) -> int | None:
        for t, ms in self.teams.items():
            if any(m.student_no == no for m in ms):
                return t
        return None

    def pending_of(self, no: str) -> Pending | None:
        return next((p for p in self.pending if p.applicant.student_no == no), None)


_SNAPSHOT_SQL = """
select
  (select coalesce(json_agg(json_build_object(
      'id', s.id, 'no', s.student_no, 'name', s.name, 'main', s.main_role, 'admin', s.is_admin,
      'subs', (select coalesce(json_agg(r.role order by r.ord), '[]'::json)
               from tf_student_sub_roles r where r.student_id = s.id)) order by s.id), '[]'::json)
   from tf_students s) as students,
  (select coalesce(json_agg(t.id order by t.id), '[]'::json) from tf_teams t) as teams,
  (select coalesce(json_agg(json_build_object('team', m.team_id, 'sid', m.student_id)
      order by m.team_id, m.slot_no), '[]'::json) from tf_members m) as members,
  (select coalesce(json_agg(json_build_object('id', a.id, 'team', a.team_id, 'sid', a.student_id)
      order by a.id), '[]'::json) from tf_applications a where a.status = '대기') as pending,
  (select coalesce(json_agg(json_build_object('app', v.application_id, 'voter', v.voter_id, 'vote', v.vote)),
      '[]'::json) from tf_votes v join tf_applications a on a.id = v.application_id
   where a.status = '대기') as votes,
  (select coalesce(json_object_agg(key, value), '{}'::json) from tf_settings) as settings
"""


def _read(cur) -> Snapshot:
    """화면 한 번에 필요한 상태를 질의 한 번으로 읽는다(DB 왕복을 줄이기 위함)."""
    cur.execute(_SNAPSHOT_SQL)
    row = cur.fetchone()
    by_id: dict[int, Student] = {}
    students: dict[str, Student] = {}
    ids: dict[str, int] = {}
    for s in row["students"]:
        if s["admin"]:
            continue
        st = Student(s["no"], s["name"], s["main"], tuple(s["subs"]))
        by_id[s["id"]] = st
        students[st.student_no] = st
        ids[st.student_no] = s["id"]
    teams: Teams = {t: [] for t in row["teams"]}
    placed = set()
    for m in row["members"]:
        teams[m["team"]].append(by_id[m["sid"]])
        placed.add(m["sid"])
    votes: dict[int, dict[str, str]] = {}
    for v in row["votes"]:
        voter = by_id.get(v["voter"])
        if voter:
            votes.setdefault(v["app"], {})[voter.student_no] = v["vote"]
    pending = [Pending(p["id"], by_id[p["sid"]], p["team"], votes.get(p["id"], {})) for p in row["pending"]]
    settings = row["settings"]
    return Snapshot(
        closed=settings.get("closed") == "true",
        confirmed=settings.get("confirmed") == "true",
        teams=teams,
        unassigned=[s for sid, s in by_id.items() if sid not in placed],
        pending=pending,
        plan=json.loads(settings["plan"]) if settings.get("plan") else None,
        _students=students,
        _ids=ids,
    )


def load_snapshot(conn) -> Snapshot:
    with conn.cursor() as cur:
        snap = _read(cur)
    conn.commit()
    return snap


def _is_admin(cur, actor_no: str) -> bool:
    cur.execute("select is_admin from tf_students where student_no = %s", (actor_no,))
    row = cur.fetchone()
    return bool(row and row["is_admin"])


def _set(cur, key: str, value: str) -> None:
    cur.execute("insert into tf_settings (key, value) values (%s, %s) "
                "on conflict (key) do update set value = excluded.value", (key, value))


def _lock_all_teams(cur) -> None:
    cur.execute("select id from tf_teams order by id for update")


def _add_member(cur, snap: Snapshot, team_no: int, student: Student) -> None:
    cur.execute("select slot_no from tf_members where team_id = %s", (team_no,))
    used = {r["slot_no"] for r in cur.fetchall()}
    slot = min(set(range(1, rules.TEAM_MAX + 1)) - used)
    cur.execute("insert into tf_members (team_id, slot_no, student_id) values (%s, %s, %s)",
                (team_no, slot, snap._ids[student.student_no]))


_NOT_ADMIN = Outcome("막힘", "관리자만 할 수 있음")


def reset_roster(conn, actor_no: str, students: list[Student], team_count: int) -> Outcome:
    """명단으로 처음 상태를 만든다(공고 2.6절). 관리자 계정과 AI 호출 기록은 남긴다."""
    with conn.cursor() as cur:
        if not _is_admin(cur, actor_no):
            conn.rollback()
            return _NOT_ADMIN
        if team_count < 1:
            conn.rollback()
            return Outcome("막힘", "팀 수는 1 이상이어야 함")
        cur.execute("delete from tf_votes")
        cur.execute("delete from tf_applications")
        cur.execute("delete from tf_members")
        cur.execute("delete from tf_teams")
        cur.execute("delete from tf_settings")
        cur.execute("delete from tf_students where not is_admin")
        rows = execute_values(
            cur,
            "insert into tf_students (student_no, name, main_role, password_hash) values %s returning id",
            [(s.student_no, s.name, s.main_role, auth.hash_password(auth.STUDENT_PASSWORD)) for s in students],
            fetch=True,
        )
        subs = [(r["id"], role, i) for r, s in zip(rows, students) for i, role in enumerate(s.sub_roles)]
        if subs:
            execute_values(cur, "insert into tf_student_sub_roles (student_id, role, ord) values %s", subs)
        execute_values(cur, "insert into tf_teams (id, name) values %s",
                       [(t, f"팀{t}") for t in range(1, team_count + 1)])
    conn.commit()
    return Outcome("승인", f"명단 {len(students)}명과 팀 {team_count}개로 처음 상태를 만듦")


def apply(conn, student_no: str, team_no: int) -> Outcome:
    try:
        with conn.cursor() as cur:
            cur.execute("select id from tf_teams where id = %s for update", (team_no,))
            if cur.fetchone() is None:
                conn.rollback()
                return Outcome("막힘", "없는 팀임")
            snap = _read(cur)
            applicant = snap.student(student_no)
            if applicant is None:
                conn.rollback()
                return Outcome("막힘", "명단에 있는 학생만 지원할 수 있음")
            members = snap.teams[team_no]
            reason = rules.apply_block_reason(
                closed=snap.closed,
                has_team=snap.team_of(student_no) is not None,
                has_pending=snap.pending_of(student_no) is not None,
                members=members,
                applicant=applicant,
            )
            if reason:
                conn.rollback()
                return Outcome("막힘", reason)
            sid = snap._ids[student_no]
            if not members:
                _add_member(cur, snap, team_no, applicant)
                cur.execute("insert into tf_applications (team_id, student_id, status, decided_at) "
                            "values (%s, %s, '승인', now())", (team_no, sid))
                conn.commit()
                return Outcome("승인", f"팀{team_no}에 들어감")
            cur.execute("insert into tf_applications (team_id, student_id, status) values (%s, %s, '대기')",
                        (team_no, sid))
        conn.commit()
        return Outcome("대기", "팀원의 투표를 기다림")
    except psycopg2.errors.UniqueViolation:
        # 같은 학생의 지원이 동시에 두 번 들어온 경우. DB 제약이 먼저 도착한 것만 남긴다.
        conn.rollback()
        snap = load_snapshot(conn)
        if snap.team_of(student_no) is not None:
            return Outcome("막힘", rules.R_HAS_TEAM)
        if snap.pending_of(student_no) is not None:
            return Outcome("막힘", rules.R_PENDING)
        return Outcome("막힘", rules.R_FULL)


def vote(conn, voter_no: str, applicant_no: str, yes: bool) -> Outcome:
    with conn.cursor() as cur:
        cur.execute("select a.id, a.team_id from tf_applications a join tf_students s on s.id = a.student_id "
                    "where s.student_no = %s and a.status = '대기'", (applicant_no,))
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            return Outcome("막힘", "대기 중인 지원이 없음")
        team_no = row["team_id"]
        cur.execute("select id from tf_teams where id = %s for update", (team_no,))
        snap = _read(cur)
        p = snap.pending_of(applicant_no)
        if p is None or p.app_id != row["id"]:
            conn.rollback()
            return Outcome("막힘", "대기 중인 지원이 없음")
        if snap.closed:
            conn.rollback()
            return Outcome("막힘", rules.R_CLOSED)
        if snap.team_of(voter_no) != team_no:
            conn.rollback()
            return Outcome("막힘", "이 팀의 팀원만 투표할 수 있음")
        if voter_no in p.votes:
            conn.rollback()
            return Outcome("막힘", "이미 투표함")
        choice = "찬성" if yes else "거부"
        cur.execute("insert into tf_votes (application_id, voter_id, vote) values (%s, %s, %s)",
                    (p.app_id, snap._ids[voter_no], choice))
        members = snap.teams[team_no]
        state = rules.vote_state({m.student_no for m in members}, {**p.votes, voter_no: choice})
        if state == "거절":
            outcome = Outcome("거절", "팀원이 거부함")
        elif state == "전원찬성":
            reason = rules.recheck_reason(members, p.applicant)
            if reason:
                outcome = Outcome("거절", reason)
            else:
                _add_member(cur, snap, team_no, p.applicant)
                outcome = Outcome("승인", f"팀{team_no}에 들어감")
        else:
            conn.commit()
            return Outcome("대기", "다른 팀원의 투표를 기다림")
        cur.execute("update tf_applications set status = %s, reason = %s, decided_at = now() where id = %s",
                    (outcome.kind, outcome.message, p.app_id))
    conn.commit()
    return outcome


def close_recruitment(conn, actor_no: str) -> Outcome:
    """모집 마감(공고 2.5절 1~2항): 대기 지원 거절, 1명뿐인 팀의 학생을 팀에서 뺌."""
    with conn.cursor() as cur:
        if not _is_admin(cur, actor_no):
            conn.rollback()
            return _NOT_ADMIN
        _lock_all_teams(cur)
        snap = _read(cur)
        if snap.closed:
            conn.rollback()
            return Outcome("막힘", "이미 마감됨")
        _set(cur, "closed", "true")
        cur.execute("update tf_applications set status = '거절', reason = '모집 마감', decided_at = now() "
                    "where status = '대기'")
        cur.execute("delete from tf_members where team_id in "
                    "(select team_id from tf_members group by team_id having count(*) = 1)")
    conn.commit()
    return Outcome("승인", "모집을 마감함")


def save_plan(conn, actor_no: str, assignments: dict[str, int], source: str) -> None:
    with conn.cursor() as cur:
        if not _is_admin(cur, actor_no):
            conn.rollback()
            raise PermissionError("관리자만 할 수 있음")
        _set(cur, "plan", json.dumps({"assignments": assignments, "source": source}, ensure_ascii=False))
    conn.commit()


def confirm_plan(conn, actor_no: str) -> Outcome:
    with conn.cursor() as cur:
        if not _is_admin(cur, actor_no):
            conn.rollback()
            return _NOT_ADMIN
        _lock_all_teams(cur)
        snap = _read(cur)
        blocked = None
        if not snap.closed:
            blocked = "모집을 먼저 마감해야 함"
        elif snap.confirmed:
            blocked = "이미 확정함"
        elif not snap.plan:
            blocked = "확정할 배정안이 없음"
        if blocked:
            conn.rollback()
            return Outcome("막힘", blocked)
        pairs = [(no, int(t)) for no, t in snap.plan["assignments"].items()]
        errors = rules.validate_plan(snap.teams, snap.unassigned, pairs)
        if errors:
            conn.rollback()
            return Outcome("막힘", "배정안이 지금 상태와 맞지 않음(" + errors[0] + ")")
        for no, t in sorted(pairs, key=lambda p: p[1]):
            _add_member(cur, snap, t, snap.student(no))
        _set(cur, "confirmed", "true")
    conn.commit()
    return Outcome("승인", "배정안을 확정함")


def log_ai(conn, attempt: int, model: str, outcome: str, detail: str, elapsed: float) -> None:
    with conn.cursor() as cur:
        cur.execute("insert into tf_ai_logs (attempt, model, outcome, detail, elapsed_sec) values (%s, %s, %s, %s, %s)",
                    (attempt, model, outcome, detail[:500], round(elapsed, 1)))
    conn.commit()


def recent_ai_logs(conn, limit: int = 20) -> list[dict]:
    """최근 AI 호출 기록. 시각은 한국 시각(UTC+9, 서머타임 없음)으로 바꾼다(배포 서버와 DB는 UTC)."""
    with conn.cursor() as cur:
        cur.execute("select to_char((created_at at time zone 'UTC') + interval '9 hours', 'MM-DD HH24:MI:SS') as at, "
                    "attempt, model, outcome, detail, elapsed_sec from tf_ai_logs order by id desc limit %s",
                    (limit,))
        rows = [dict(r) for r in cur.fetchall()]
    conn.commit()
    return rows
