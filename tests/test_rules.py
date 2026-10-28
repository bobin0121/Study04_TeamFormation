# 생성: 2026-10-28 19:36 KST
from rules import (
    PL, WP, R_CLOSED, R_FULL, R_HAS_TEAM, R_PENDING, R_REQUIRED, R_SAME_MAIN,
    Student, apply_block_reason, can_take, filled_required_count, recheck_reason,
    required_slot_ok, vote_state,
)


def T(no, main, *subs):
    return Student(no, f"s{no}", main, tuple(subs))


def test_can_take_uses_main_and_sub_roles():
    s = T("1", "테스터", PL)
    assert can_take(s, "테스터") and can_take(s, PL) and not can_take(s, WP)


def test_filled_required_counts_distinct_people():
    assert filled_required_count([T("1", PL, WP)]) == 1          # 공고 예: 혼자 둘 다 해도 1
    assert filled_required_count([T("1", PL), T("2", WP)]) == 2
    assert filled_required_count([T("1", "테스터", PL), T("2", "프론트엔드 디자이너", WP)]) == 2
    assert filled_required_count([T("1", "테스터"), T("2", "발표자")]) == 0
    assert filled_required_count([T("1", PL, WP), T("2", "테스터", PL)]) == 2   # 1이 WP, 2가 PL
    assert filled_required_count([T("1", PL, WP), T("2", PL)]) == 2


def test_required_slot_examples_from_notice():
    # 테스터, 발표자 팀에 보고서 작성자: 남는 자리 1 < 2 -> 막음
    assert not required_slot_ok([T("1", "테스터"), T("2", "발표자"), T("3", "보고서 작성자")])
    # 같은 팀에 기획자: 남는 자리 1, 채우지 못한 역할 1 -> 통과(PRD 4.1 해석)
    assert required_slot_ok([T("1", "테스터"), T("2", "발표자"), T("3", PL)])
    # 남는 자리 2, 채우지 못한 역할 2 -> 통과(부록 3의 10단계)
    assert required_slot_ok([T("1", "테스터", "발표자"), T("2", "발표자", "프론트엔드 디자이너")])
    # 4명이 다 찼는데 웹 프로그래머가 없음 -> 막음
    assert not required_slot_ok([T("1", PL), T("2", "테스터"), T("3", "발표자"), T("4", "보고서 작성자")])


def test_apply_block_order():
    a = T("9", PL)
    full = [T(str(i), r) for i, r in enumerate(["테스터", "발표자", WP, "보고서 작성자"])]
    assert apply_block_reason(closed=True, has_team=True, has_pending=True, members=full, applicant=a) == R_CLOSED
    assert apply_block_reason(closed=False, has_team=True, has_pending=True, members=full, applicant=a) == R_HAS_TEAM
    assert apply_block_reason(closed=False, has_team=False, has_pending=True, members=full, applicant=a) == R_PENDING
    assert apply_block_reason(closed=False, has_team=False, has_pending=False, members=full, applicant=a) == R_FULL
    assert apply_block_reason(closed=False, has_team=False, has_pending=False, members=[T("1", PL)], applicant=a) == R_SAME_MAIN
    assert apply_block_reason(closed=False, has_team=False, has_pending=False,
                              members=[T("1", "테스터"), T("2", "발표자")], applicant=T("3", "보고서 작성자")) == R_REQUIRED
    assert apply_block_reason(closed=False, has_team=False, has_pending=False, members=[], applicant=a) is None


def test_block_messages_are_exact():
    assert R_CLOSED == "모집이 마감됨"
    assert R_HAS_TEAM == "이미 팀이 있음"
    assert R_PENDING == "결과를 기다리는 지원이 있음"
    assert R_FULL == "팀이 꽉 참"
    assert R_SAME_MAIN == "같은 주 역할의 팀원이 있음"
    assert R_REQUIRED == "필수 포함 역할(기획자, 웹 프로그래머)을 맡을 학생의 자리가 모자람"


def test_recheck_same_main_role():
    members = [T("2", PL, "발표자"), T("8", "프론트엔드 디자이너", "테스터"), T("5", WP, "프론트엔드 디자이너")]
    assert recheck_reason(members, T("6", WP, "보고서 작성자")) == "승인 직전 검사에서 같은 주 역할의 팀원이 있음"
    assert recheck_reason(members[:2], T("5", WP)) is None


def test_recheck_full_and_required():
    four = [T("1", PL), T("2", WP), T("3", "테스터"), T("4", "발표자")]
    assert recheck_reason(four, T("5", "보고서 작성자")) == "승인 직전 검사에서 팀이 꽉 참"
    two = [T("1", "테스터"), T("2", "발표자")]
    assert recheck_reason(two, T("3", "보고서 작성자")) == "승인 직전 검사에서 필수 포함 역할을 맡을 학생의 자리가 모자람"


def test_vote_state():
    assert vote_state({"1", "4"}, {"1": "찬성"}) == "대기"
    assert vote_state({"1", "4"}, {"1": "찬성", "4": "찬성"}) == "전원찬성"
    assert vote_state({"1", "4"}, {"1": "찬성", "4": "거부"}) == "거절"
    assert vote_state({"1"}, {"1": "찬성", "99": "거부"}) == "전원찬성"   # 팀원이 아닌 표는 무시
    assert vote_state({"1", "4"}, {"4": "거부"}) == "거절"                 # 한 명이라도 거부면 바로 거절
