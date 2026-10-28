-- 생성: 2026-10-28 19:40 KST
-- 팀 편성 앱의 tf_ 테이블. 앱이 시작할 때 이 파일을 그대로 실행한다(db.apply_schema).

create table if not exists tf_students (
  id serial primary key,
  student_no text not null unique,
  name text not null,
  main_role text check (main_role in ('기획자','웹 프로그래머','프론트엔드 디자이너','테스터','보고서 작성자','발표자')),
  password_hash text not null,
  is_admin boolean not null default false,
  check (is_admin or main_role is not null)
);

create table if not exists tf_student_sub_roles (
  student_id integer not null references tf_students(id) on delete cascade,
  role text not null check (role in ('기획자','웹 프로그래머','프론트엔드 디자이너','테스터','보고서 작성자','발표자')),
  ord smallint not null default 0,  -- CSV에 적힌 순서
  primary key (student_id, role)
);

create table if not exists tf_teams (
  id integer primary key,
  name text not null unique
);

-- (team_id, slot_no) 기본 키와 student_id 유일 제약이 "마지막 자리에 먼저 도착한 학생만 기록"과
-- "한 학생은 한 팀에만 소속"을 DB에서 지킨다. slot_no 검사는 다섯 번째 자리를 막는다.
create table if not exists tf_members (
  team_id integer not null references tf_teams(id) on delete cascade,
  slot_no integer not null check (slot_no between 1 and 4),
  student_id integer not null unique references tf_students(id) on delete cascade,
  primary key (team_id, slot_no)
);

create table if not exists tf_applications (
  id serial primary key,
  team_id integer not null references tf_teams(id) on delete cascade,
  student_id integer not null references tf_students(id) on delete cascade,
  status text not null check (status in ('대기','승인','거절')),
  reason text,
  created_at timestamptz not null default now(),
  decided_at timestamptz
);

-- 결과를 기다리는 지원은 학생당 1개
create unique index if not exists tf_applications_one_pending
  on tf_applications (student_id) where status = '대기';

create table if not exists tf_votes (
  application_id integer not null references tf_applications(id) on delete cascade,
  voter_id integer not null references tf_students(id) on delete cascade,
  vote text not null check (vote in ('찬성','거부')),
  created_at timestamptz not null default now(),
  primary key (application_id, voter_id)
);

create table if not exists tf_settings (
  key text primary key,
  value text not null
);

create table if not exists tf_ai_logs (
  id serial primary key,
  attempt integer not null,
  model text not null,
  outcome text not null,
  detail text,
  elapsed_sec numeric(6,1),
  created_at timestamptz not null default now()
);
