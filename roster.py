# 생성: 2026-10-28 19:39 KST
"""명단 CSV 읽기(PRD 8장). BOM이 있어도 읽도록 utf-8-sig로 읽는다."""

import csv
import io

from rules import ROLES, Student

HEADER = ["student_no", "name", "main_role", "sub_roles"]
ADMIN_NO = "admin"


class RosterError(ValueError):
    pass


def parse_roster(data: bytes) -> list[Student]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise RosterError("CSV를 UTF-8로 읽을 수 없음") from None

    reader = csv.reader(io.StringIO(text))
    students: list[Student] = []
    seen: set[str] = set()
    header_done = False
    for row in reader:
        cells = [c.strip() for c in row]
        if not any(cells):
            continue
        line = reader.line_num
        if not header_done:
            if cells != HEADER:
                raise RosterError("CSV 첫 줄(머리글)이 student_no,name,main_role,sub_roles가 아님")
            header_done = True
            continue
        if len(cells) != 4:
            raise RosterError(f"CSV {line}번째 줄의 열이 {len(cells)}개임(4개여야 함)")
        no, name, main, subs_text = cells
        if not no or not name:
            raise RosterError(f"CSV {line}번째 줄의 학번이나 이름이 비어 있음")
        if no == ADMIN_NO:
            raise RosterError(f"CSV {line}번째 줄의 학번 admin은 관리자 학번이라 쓸 수 없음")
        if no in seen:
            raise RosterError(f"CSV {line}번째 줄의 학번이 앞줄과 겹침({no})")
        if main not in ROLES:
            raise RosterError(f"CSV {line}번째 줄의 주 역할이 6개 역할에 없음")
        subs = tuple(dict.fromkeys(s.strip() for s in subs_text.split(";") if s.strip()))
        if len(subs) > 2:
            raise RosterError(f"CSV {line}번째 줄의 보조 역할이 2개보다 많음")
        if any(s not in ROLES for s in subs):
            raise RosterError(f"CSV {line}번째 줄의 보조 역할이 6개 역할에 없음")
        seen.add(no)
        students.append(Student(no, name, main, subs))

    if not students:
        raise RosterError("CSV에 학생이 없음")
    return students
