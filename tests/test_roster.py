# 생성: 2026-10-28 19:39 KST
import pytest

from roster import RosterError, parse_roster
from tests.scenarios import FIXTURES

HEADER = "student_no,name,main_role,sub_roles\n"


def test_bom_crlf_trailing_blank_and_empty_subroles():
    data = ("﻿student_no,name,main_role,sub_roles\r\n2026001,가나다,기획자,보고서 작성자\r\n"
            "2026002,라마바,웹 프로그래머,\r\n2026003,사아자,테스터,기획자;발표자\r\n\r\n").encode("utf-8")
    s = parse_roster(data)
    assert [x.student_no for x in s] == ["2026001", "2026002", "2026003"]
    assert [x.sub_roles for x in s] == [("보고서 작성자",), (), ("기획자", "발표자")]
    assert s[1].main_role == "웹 프로그래머"


def test_no_bom_and_outer_spaces_are_trimmed():
    s = parse_roster((HEADER + " 1 , a , 웹 프로그래머 , 기획자 ; 보고서 작성자 \n").encode("utf-8"))
    assert s[0].student_no == "1" and s[0].name == "a"
    assert s[0].main_role == "웹 프로그래머"
    assert s[0].sub_roles == ("기획자", "보고서 작성자")


def test_errors_name_the_line():
    with pytest.raises(RosterError, match="3번째 줄"):
        parse_roster((HEADER + "1,a,기획자,\n2,b,요리사,\n").encode())
    with pytest.raises(RosterError, match="열"):        # 쉼표를 지워 열이 3개
        parse_roster((HEADER + "1,a,기획자\n").encode())
    with pytest.raises(RosterError, match="겹침"):
        parse_roster((HEADER + "1,a,기획자,\n1,b,테스터,\n").encode())
    with pytest.raises(RosterError, match="admin"):
        parse_roster((HEADER + "admin,a,기획자,\n").encode())
    with pytest.raises(RosterError, match="보조 역할"):
        parse_roster((HEADER + "1,a,기획자,테스터;발표자;보고서 작성자\n").encode())
    with pytest.raises(RosterError, match="보조 역할"):
        parse_roster((HEADER + "1,a,기획자,요리사\n").encode())
    with pytest.raises(RosterError, match="머리글"):
        parse_roster("번호,이름,역할,보조\n1,a,기획자,\n".encode())
    with pytest.raises(RosterError, match="학생이 없음"):
        parse_roster(HEADER.encode())
    with pytest.raises(RosterError, match="UTF-8"):
        parse_roster((HEADER + "1,가,기획자,\n").encode("cp949"))


def test_fixture_files_parse():
    for name, n in [("쉬움.csv", 8), ("중간.csv", 12), ("어려움.csv", 16)]:
        assert len(parse_roster((FIXTURES / name).read_bytes())) == n
    hard = parse_roster((FIXTURES / "어려움.csv").read_bytes())
    assert hard[12].name == "학생13(RW;PT;FD)"
    assert hard[12].sub_roles == ("발표자", "프론트엔드 디자이너")
    assert hard[15].sub_roles == ()
