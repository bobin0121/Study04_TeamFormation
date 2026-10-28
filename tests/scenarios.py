# 생성: 2026-10-28 19:39 KST
"""공고 부록의 연습 시나리오 3개를 동작 단위로 나눈 것.

지원 단추의 결과는 공고 2.4절(빈 팀이면 승인, 팀원이 있으면 대기)을, 찬성과 거부의 결과는
그 지원의 지금 상태(공고 2.7절)를 따른다. 테스트(tests/)와 브라우저 검증(e2e/)만 쓴다.
"""

from dataclasses import dataclass, field
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


@dataclass(frozen=True)
class Action:
    actor: str                 # 학번 또는 "admin"
    kind: str                  # "apply" | "yes" | "no" | "close" | "assign_confirm"
    target: str | int | None   # apply: 팀 번호, yes/no: 지원자 학번
    expect: str                # 결과 안내의 첫 단어
    expect_unassigned: tuple[str, ...] = field(default=())   # close 뒤 unassigned에 있어야 할 이름


@dataclass(frozen=True)
class Scenario:
    csv_name: str
    team_count: int
    actions: list[Action]


def _ap(prefix, who, team, expect):
    return Action(prefix + who, "apply", team, expect)


def _v(prefix, who, yes, applicant, expect):
    return Action(prefix + who, "yes" if yes else "no", prefix + applicant, expect)


def _easy():
    p = "20261"
    return [
        _ap(p, "01", 1, "승인"), _ap(p, "02", 2, "승인"), _ap(p, "03", 3, "승인"),             # 1
        _ap(p, "04", 1, "대기"), _v(p, "01", True, "04", "승인"),                                 # 2
        _ap(p, "05", 2, "대기"), _v(p, "02", True, "05", "승인"),                                 # 3
        _ap(p, "07", 1, "대기"), _v(p, "01", True, "07", "대기"), _v(p, "04", False, "07", "거절"),  # 4
        _ap(p, "06", 3, "대기"), _v(p, "03", True, "06", "승인"),                                 # 5
        Action("admin", "close", None, "승인"),                                                   # 6
        Action("admin", "assign_confirm", None, "승인"),
    ]


def _medium():
    p = "20262"
    return [
        _ap(p, "01", 1, "승인"),                                                                  # 1
        _ap(p, "05", 1, "대기"), _v(p, "01", True, "05", "승인"),                                 # 2
        _ap(p, "02", 1, "막힘"),                                                                  # 3 (투표는 건너뜀)
        _ap(p, "06", 2, "승인"),                                                                  # 4
        _ap(p, "09", 2, "대기"), _v(p, "06", True, "09", "승인"),                                 # 5
        _ap(p, "10", 2, "대기"), _v(p, "06", True, "10", "대기"), _v(p, "09", False, "10", "거절"),  # 6
        _ap(p, "03", 3, "승인"), _ap(p, "11", 4, "승인"),                                         # 7
        _ap(p, "12", 4, "대기"), _ap(p, "12", 3, "막힘"),                                         # 8
        Action("admin", "close", None, "승인",
               ("학생3(PL;RW)", "학생11(RW)", "학생12(PT;RW;FD)")),                             # 9
        _ap(p, "02", 3, "막힘"),                                                                  # 10
        Action("admin", "assign_confirm", None, "승인"),                                         # 11
    ]


def _hard():
    p = "20263"
    return [
        _ap(p, "01", 1, "승인"),                                                                  # 1
        _ap(p, "04", 1, "대기"), _v(p, "01", True, "04", "승인"),                                 # 2
        _ap(p, "07", 1, "대기"), _v(p, "01", True, "07", "대기"), _v(p, "04", True, "07", "승인"),   # 3
        _ap(p, "02", 2, "승인"),                                                                  # 4
        _ap(p, "08", 2, "대기"), _v(p, "02", True, "08", "승인"),                                 # 5
        _ap(p, "05", 2, "대기"), _ap(p, "06", 2, "대기"),                                         # 6
        _v(p, "02", True, "05", "대기"), _v(p, "08", True, "05", "승인"),                         # 7
        _v(p, "02", True, "06", "대기"), _v(p, "08", True, "06", "대기"), _v(p, "05", True, "06", "거절"),  # 8
        _ap(p, "11", 3, "승인"),                                                                  # 9
        _ap(p, "15", 3, "대기"), _v(p, "11", True, "15", "승인"),                                 # 10
        _ap(p, "14", 3, "막힘"),                                                                  # 11 (투표는 건너뜀)
        _ap(p, "10", 4, "승인"),                                                                  # 12
        _ap(p, "13", 1, "대기"), _v(p, "01", True, "13", "대기"),                                 # 13
        Action("admin", "close", None, "승인", ("학생10(TT;RW)", "학생13(RW;PT;FD)")),             # 14
        Action("admin", "assign_confirm", None, "승인"),                                         # 15
    ]


SCENARIOS = {
    "쉬움": Scenario("쉬움.csv", 3, _easy()),
    "중간": Scenario("중간.csv", 4, _medium()),
    "어려움": Scenario("어려움.csv", 4, _hard()),
}
