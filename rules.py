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


def vote_state(member_nos: Collection[str], votes: Mapping[str, str]) -> str:
    """지금 팀원의 표만 센다. "거절", "전원찬성", "대기" 가운데 하나."""
    current = {no: v for no, v in votes.items() if no in member_nos}
    if any(v == "거부" for v in current.values()):
        return "거절"
    if all(current.get(no) == "찬성" for no in member_nos):
        return "전원찬성"
    return "대기"
