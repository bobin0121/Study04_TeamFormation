# 생성: 2026-10-28 19:36 KST
"""팀 편성 규칙(PRD 4장). DB와 화면을 건드리지 않는 순수 함수만 둔다."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

ROLES = ("기획자", "웹 프로그래머", "프론트엔드 디자이너", "테스터", "보고서 작성자", "발표자")
PL = "기획자"
WP = "웹 프로그래머"
TEAM_MAX = 4
TEAM_MIN = 2

# 지원이 막힌 이유(결과 안내의 "막힘: " 뒤 문구)
R_CLOSED = "모집이 마감됨"
R_HAS_TEAM = "이미 팀이 있음"
R_PENDING = "결과를 기다리는 지원이 있음"
R_FULL = "팀이 꽉 참"
R_SAME_MAIN = "같은 주 역할의 팀원이 있음"
R_REQUIRED = "필수 포함 역할(기획자, 웹 프로그래머)을 맡을 학생의 자리가 모자람"

RECHECK = "승인 직전 검사에서 "


@dataclass(frozen=True)
class Student:
    student_no: str
    name: str
    main_role: str
    sub_roles: tuple[str, ...] = ()


Teams = dict[int, list[Student]]


def can_take(s: Student, role: str) -> bool:
    return s.main_role == role or role in s.sub_roles


def filled_required_count(members: Sequence[Student]) -> int:
    """기획자와 웹 프로그래머를 서로 다른 사람으로 채울 수 있는 최대 개수(0, 1, 2)."""
    planners = [s for s in members if can_take(s, PL)]
    programmers = [s for s in members if can_take(s, WP)]
    if any(p is not w for p in planners for w in programmers):
        return 2
    return 1 if planners or programmers else 0


def required_slot_ok(members_after: Sequence[Student]) -> bool:
    """지원자를 넣은 팀에서, 남는 자리로 채우지 못한 필수 역할을 채울 수 있는가."""
    return TEAM_MAX - len(members_after) >= 2 - filled_required_count(members_after)


def _team_reason(members: Sequence[Student], applicant: Student, required: str) -> str | None:
    if len(members) >= TEAM_MAX:
        return R_FULL
    if any(m.main_role == applicant.main_role for m in members):
        return R_SAME_MAIN
    if not required_slot_ok([*members, applicant]):
        return required
    return None


def apply_block_reason(*, closed: bool, has_team: bool, has_pending: bool,
                       members: Sequence[Student], applicant: Student) -> str | None:
    """지원 단추를 누를 때의 막힘 검사(PRD 4.2절). 통과하면 None."""
    if closed:
        return R_CLOSED
    if has_team:
        return R_HAS_TEAM
    if has_pending:
        return R_PENDING
    return _team_reason(members, applicant, R_REQUIRED)


def recheck_reason(members: Sequence[Student], applicant: Student) -> str | None:
    """모든 팀원이 찬성했을 때 승인 직전에 다시 하는 검사(PRD 4.4절). 통과하면 None."""
    reason = _team_reason(members, applicant, "필수 포함 역할을 맡을 학생의 자리가 모자람")
    return RECHECK + reason if reason else None


def team_errors(team_no: int, members: Sequence[Student]) -> list[str]:
    """확정할 팀 구성의 규칙 위반(인원, 주 역할 중복, 필수 포함 역할)."""
    errors = []
    if not TEAM_MIN <= len(members) <= TEAM_MAX:
        errors.append(f"팀{team_no}: 인원 {len(members)}명(2~4명이어야 함)")
    mains = [m.main_role for m in members]
    for role in ROLES:
        if mains.count(role) > 1:
            errors.append(f"팀{team_no}: 주 역할 {role} 중복")
    if filled_required_count(members) < 2:
        errors.append(f"팀{team_no}: 기획자와 웹 프로그래머를 서로 다른 학생이 맡을 수 없음")
    return errors


def validate_plan(teams: Teams, unassigned: Sequence[Student],
                  assignments: Sequence[tuple[str, int]]) -> list[str]:
    """배정안 검사 다섯 가지(PRD 4.6절). 빈 목록이면 통과."""
    errors = []
    pool = {s.student_no: s for s in unassigned}
    placed = {m.student_no for ms in teams.values() for m in ms}
    result = {t: list(ms) for t, ms in teams.items()}
    seen = set()
    for no, team_no in assignments:
        if no in seen:
            errors.append(f"{no}: 두 번 배정됨")
            continue
        seen.add(no)
        if no in placed:
            errors.append(f"{no}: 이미 팀이 있는 학생임")
        elif no not in pool:
            errors.append(f"{no}: 팀이 없는 학생 명단에 없음")
        elif team_no not in result:
            errors.append(f"{no}: 없는 팀 번호({team_no})에 배정됨")
        else:
            result[team_no].append(pool[no])
    for s in unassigned:
        if s.student_no not in seen:
            errors.append(f"{s.name}({s.student_no}): 배정안에서 빠짐")
    for t in sorted(result):
        errors.extend(team_errors(t, result[t]))
    return errors


def _fits(s: Student, teams: Teams) -> list[int]:
    return [t for t, ms in teams.items()
            if len(ms) < TEAM_MAX and all(m.main_role != s.main_role for m in ms)]


def find_assignment(teams: Teams, unassigned: Sequence[Student]) -> dict[str, int] | None:
    """검사 다섯 가지를 모두 통과하는 배정을 모든 경우를 따져 찾는다(PRD 4.7절). 없으면 None."""
    order = sorted(unassigned, key=lambda s: len(_fits(s, teams)))
    cur = {t: list(ms) for t, ms in teams.items()}
    plan: dict[str, int] = {}

    def short_of_min() -> int:
        return sum(max(0, TEAM_MIN - len(ms)) for ms in cur.values())

    def go(i: int) -> bool:
        if short_of_min() > len(order) - i:
            return False
        if i == len(order):
            return all(not team_errors(t, ms) for t, ms in cur.items())
        s = order[i]
        tried_empty = False
        for t in sorted(cur):
            ms = cur[t]
            if len(ms) >= TEAM_MAX or any(m.main_role == s.main_role for m in ms):
                continue
            if not ms:
                if tried_empty:
                    continue  # 빈 팀끼리는 서로 바꿔도 같은 배정
                tried_empty = True
            ms.append(s)
            plan[s.student_no] = t
            if not (len(ms) == TEAM_MAX and filled_required_count(ms) < 2) and go(i + 1):
                return True
            ms.pop()
            del plan[s.student_no]
        return False

    return dict(plan) if go(0) else None


def infeasibility_reasons(teams: Teams, unassigned: Sequence[Student]) -> list[str]:
    """규칙을 지키는 배정이 없을 때 보여 줄 이유(PRD 4.8절)."""
    reasons = []
    total = sum(len(ms) for ms in teams.values()) + len(unassigned)
    if not TEAM_MIN * len(teams) <= total <= TEAM_MAX * len(teams):
        reasons.append("학생 수로는 모든 팀을 2~4명으로 만들 수 없음")
    for t in sorted(teams):
        ms = teams[t]
        if filled_required_count(ms) == 2:
            continue
        if len(ms) >= TEAM_MAX:
            candidates = []
        else:
            mains = {m.main_role for m in ms}
            candidates = [s for s in unassigned if s.main_role not in mains]
        missing = [role for role in (PL, WP)
                   if not any(can_take(s, role) for s in [*ms, *candidates])]
        for role in missing:
            reasons.append(f"팀{t}에 {role}를 맡을 학생이 없음")
        if not missing and len(ms) >= TEAM_MAX:
            reasons.append(f"팀{t}에 기획자와 웹 프로그래머를 서로 다른 학생이 맡을 수 없음")
    return reasons or ["역할 조합으로는 모든 규칙을 함께 지킬 수 없음"]


def vote_state(member_nos: Collection[str], votes: Mapping[str, str]) -> str:
    """지금 팀원의 표만 센다. "거절", "전원찬성", "대기" 가운데 하나."""
    current = {no: v for no, v in votes.items() if no in member_nos}
    if any(v == "거부" for v in current.values()):
        return "거절"
    if all(current.get(no) == "찬성" for no in member_nos):
        return "전원찬성"
    return "대기"
