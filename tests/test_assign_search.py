# 생성: 2026-10-28 19:37 KST
import itertools
import random

from rules import (
    PL, ROLES, WP, Student, find_assignment, infeasibility_reasons, team_errors, validate_plan,
)
from tests.states import hard_after_close


def test_hard_scenario_final_state_has_assignment():
    teams, unassigned = hard_after_close()
    plan = find_assignment(teams, unassigned)
    assert plan is not None
    assert validate_plan(teams, unassigned, list(plan.items())) == []
    assert plan["2026303"] == 3                    # 팀3에 기획자가 될 수 있는 학생은 3번뿐


def test_validate_plan_catches_each_rule():
    teams, unassigned = hard_after_close()
    good = list(find_assignment(teams, unassigned).items())
    assert any("빠짐" in e for e in validate_plan(teams, unassigned, good[1:]))
    assert any("두 번" in e for e in validate_plan(teams, unassigned, good + [good[0]]))
    assert any("이미 팀" in e for e in validate_plan(teams, unassigned, good + [("2026301", 4)]))
    assert any("없는 팀" in e for e in validate_plan(teams, unassigned, good[1:] + [(good[0][0], 9)]))
    assert any("명단에 없음" in e for e in validate_plan(teams, unassigned, good + [("9999999", 4)]))
    assert validate_plan(teams, unassigned, [(no, 4) for no, _ in good])   # 팀4에 8명


def test_team_errors_messages():
    s = lambda no, main, *subs: Student(no, no, main, tuple(subs))
    assert team_errors(3, [s("1", PL)]) == ["팀3: 인원 1명(2~4명이어야 함)",
                                            "팀3: 기획자와 웹 프로그래머를 서로 다른 학생이 맡을 수 없음"]
    assert "팀2: 주 역할 테스터 중복" in team_errors(2, [s("1", "테스터", PL), s("2", "테스터", WP)])
    assert team_errors(1, [s("1", "테스터", PL), s("2", "발표자", WP)]) == []


def test_no_assignment_when_full_team_lacks_wp():
    full = [Student(str(i), f"s{i}", r) for i, r in enumerate([PL, "테스터", "발표자", "보고서 작성자"])]
    teams = {1: full, 2: [], 3: []}
    unassigned = [Student("a", "a", WP), Student("b", "b", PL), Student("c", "c", WP), Student("d", "d", PL)]
    assert find_assignment(teams, unassigned) is None
    assert "팀1에 웹 프로그래머를 맡을 학생이 없음" in infeasibility_reasons(teams, unassigned)


def test_infeasible_when_no_candidate_can_fill_role():
    teams = {1: [Student("1", "1", "테스터"), Student("2", "2", "발표자")], 2: [Student("3", "3", PL), Student("4", "4", WP)]}
    unassigned = [Student("5", "5", "보고서 작성자")]
    assert find_assignment(teams, unassigned) is None
    reasons = infeasibility_reasons(teams, unassigned)
    assert "팀1에 기획자를 맡을 학생이 없음" in reasons
    assert "팀1에 웹 프로그래머를 맡을 학생이 없음" in reasons


def test_infeasible_by_head_count():
    teams = {1: [], 2: [], 3: []}
    unassigned = [Student(str(i), str(i), r) for i, r in enumerate([PL, WP, "테스터"])]
    assert find_assignment(teams, unassigned) is None
    assert "학생 수로는 모든 팀을 2~4명으로 만들 수 없음" in infeasibility_reasons(teams, unassigned)


def test_infeasibility_has_a_default_reason():
    # 팀 수와 인원은 맞고 각 팀에 후보도 있지만, 함께 지킬 수는 없는 경우
    teams = {1: [], 2: []}
    unassigned = [Student("a", "a", PL, (WP,)), Student("b", "b", "테스터"), Student("c", "c", "발표자"), Student("d", "d", "보고서 작성자")]
    assert find_assignment(teams, unassigned) is None
    assert infeasibility_reasons(teams, unassigned)


def _random_student(rng, no):
    # 필수 포함 역할을 맡을 수 있는 학생이 자주 나오게 기획자, 웹 프로그래머 쪽으로 치우쳐 뽑음
    m = rng.choice(ROLES + (PL, WP))
    others = [r for r in ROLES if r != m]
    subs = rng.sample(others, rng.choice([0, 1, 2]))
    if rng.random() < 0.4 and PL != m and PL not in subs and len(subs) < 2:
        subs.append(rng.choice([r for r in (PL, WP) if r != m]))
    return Student(str(no), str(no), m, tuple(dict.fromkeys(subs)))


def _random_state(rng):
    n_teams = rng.choice([3, 4])
    teams, no = {}, 0
    for t in range(1, n_teams + 1):
        members = []
        for _ in range(rng.choice([0, 0, 1, 2, 3])):
            no += 1
            s = _random_student(rng, no)
            if all(x.main_role != s.main_role for x in members):
                members.append(s)
        teams[t] = members
    existing = sum(len(ms) for ms in teams.values())
    low = max(0, 2 * n_teams - existing)
    k = rng.randint(min(low, 5), 5) if rng.random() < 0.8 else rng.randint(0, 5)
    unassigned = []
    for _ in range(k):
        no += 1
        unassigned.append(_random_student(rng, no))
    return teams, unassigned


def _brute_force_exists(teams, unassigned):
    for combo in itertools.product(sorted(teams), repeat=len(unassigned)):
        if not validate_plan(teams, unassigned, [(s.student_no, t) for s, t in zip(unassigned, combo)]):
            return True
    return False


def test_search_is_exhaustive_on_random_small_cases():
    rng = random.Random(20261028)
    seen = {True: 0, False: 0}
    for _ in range(400):
        teams, unassigned = _random_state(rng)
        expected = _brute_force_exists(teams, unassigned)
        plan = find_assignment(teams, unassigned)
        assert (plan is not None) == expected, (teams, unassigned)
        if plan is not None:
            assert validate_plan(teams, unassigned, list(plan.items())) == []
        seen[expected] += 1
    assert seen[True] >= 10 and seen[False] >= 10, seen
