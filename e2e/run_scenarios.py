# 생성: 2026-10-29 21:40 KST
"""채점 프로그램처럼 배포한 앱(또는 내 컴퓨터의 앱)에서 연습 시나리오를 돌린다.

- 관리자와 학생마다 브라우저 컨텍스트를 따로 연다.
- 화면 요소는 공고 2.7절의 key(st-key-… 클래스)로만 찾는다.
- 동작마다 단추가 나타나기를 7초까지 기다리고, 단추가 없거나 비활성이면 "막힘"으로 본다.
- 누른 뒤 result의 첫 단어(쌍점 앞)를 기대 결과와 비교한다.
- 마지막에 새 컨텍스트로 관리자 로그인을 해서 확정한 팀 구성이 규칙을 지키는지 검사한다.

사용: python e2e/run_scenarios.py --url URL --scenario 어려움 [--admin-password-env ADMIN_PASSWORD]
관리자 비밀번호는 환경 변수(없으면 .env)에서 읽고 출력하지 않는다.
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import TimeoutError as PWTimeout  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

import config  # noqa: E402
from roster import parse_roster  # noqa: E402
from rules import team_errors  # noqa: E402
from tests.scenarios import FIXTURES, SCENARIOS  # noqa: E402

BUTTON_WAIT_MS = 7000          # 채점 프로그램과 같음
RESULT_WAIT_MS = 15000
ASSIGN_WAIT_MS = 10 * 60 * 1000  # AI 배정은 최대 10분까지 기다림(공고 6.3절 18번)
STUDENT_PASSWORD = "1234"


def first_word(text: str) -> str:
    return re.split(r"[:\s]", text.strip(), maxsplit=1)[0] if text and text.strip() else ""


class Grader:
    def __init__(self, browser, url, admin_pw, debug_dir=None):
        self.browser, self.url, self.admin_pw = browser, url.rstrip("/"), admin_pw
        self.debug_dir = Path(debug_dir) if debug_dir else None
        self.pages = {}
        self.failures = 0
        self.step = 0

    def page_for(self, who):
        if who not in self.pages:
            ctx = self.browser.new_context()
            page = ctx.new_page()
            self.login(page, who, self.admin_pw if who == "admin" else STUDENT_PASSWORD)
            self.pages[who] = page
        return self.pages[who]

    def login(self, page, who, pw):
        page.goto(self.url, wait_until="domcontentloaded")
        frame = self.app_frame(page)
        frame.locator(".st-key-login_student_no input").wait_for(timeout=120000)
        frame.locator(".st-key-login_student_no input").fill(who)
        frame.locator(".st-key-login_password input").fill(pw)
        frame.locator(".st-key-login_submit button").click()
        frame.locator(".st-key-whoami").wait_for(timeout=30000)

    @staticmethod
    def app_frame(page):
        # Streamlit Community Cloud는 앱을 iframe 안에 띄운다. 내 컴퓨터에서는 iframe이 없다.
        for _ in range(60):
            for f in page.frames:
                try:
                    if f.locator(".st-key-login_student_no, .st-key-whoami").count():
                        return f
                except Exception:
                    pass
            time.sleep(1)
        return page.main_frame

    def result_text(self, frame):
        loc = frame.locator(".st-key-result")
        return loc.inner_text().strip() if loc.count() else ""

    def press(self, who, key, wait_ms=RESULT_WAIT_MS, peek=None):
        """단추를 누르고 result를 읽는다. 단추가 7초 안에 없거나 비활성이면 막힘으로 본다."""
        frame = self.app_frame(self.page_for(who))
        button = frame.locator(f".st-key-{key} button")
        try:
            button.first.wait_for(state="visible", timeout=BUTTON_WAIT_MS)
        except PWTimeout:
            self.dump(who, key, "단추 없음")
            return "막힘", "(단추 없음)"
        if button.first.is_disabled():
            return "막힘", "(단추 비활성)"
        before = self.result_text(frame)
        try:
            button.first.click(timeout=10000)
        except PWTimeout:
            if button.count() == 0 or button.first.is_disabled():
                # 누르려는 사이 화면이 갱신되어 단추가 사라지거나 비활성이 됨: 공고 규칙대로 막힘
                return "막힘", "(누르려는 사이 단추가 비활성으로 바뀜)"
            self.dump(who, key, "누르지 못함")
            return "?", "(단추를 누르지 못함)"
        start = time.time()
        if peek is not None:  # 누른 뒤 2초 때의 result(진행 중 안내 확인용)
            time.sleep(2)
            peek.append(self.result_text(frame))
        text = before
        while time.time() - start < wait_ms / 1000:
            time.sleep(0.5)
            text = self.result_text(frame)
            if first_word(text) not in ("승인", "대기", "거절", "막힘"):
                continue
            if text != before:
                break
            # 앞 안내와 글자가 같은 경우(예: 대기 다음 또 대기): 앱이 처리를 끝낼 때까지 기다린 뒤 읽는다.
            if time.time() - start >= 4 and not frame.locator('[data-testid="stStatusWidget"]').count():
                break
        return first_word(text), text

    def dump(self, who, key, why):
        """원인을 볼 수 있게 그 순간의 화면 캡처와 화면 글자를 저장한다."""
        if not self.debug_dir:
            return
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        page = self.pages[who]
        stem = f"{self.step + 1:02d}_{who}_{key}"
        page.screenshot(path=str(self.debug_dir / f"{stem}.png"), full_page=True)
        (self.debug_dir / f"{stem}.txt").write_text(
            why + "\n" + self.app_frame(page).locator("body").inner_text(), encoding="utf-8")

    def check(self, label, expect, got, detail):
        self.step += 1
        ok = got == expect
        self.failures += 0 if ok else 1
        print(f"{self.step:02d} {label} | 기대 {expect} / 실제 {got} | {'일치' if ok else '불일치'} | {detail}",
              flush=True)

    def upload(self, csv_path, team_count):
        frame = self.app_frame(self.page_for("admin"))
        frame.locator(".st-key-admin_roster_file input[type=file]").set_input_files(str(csv_path))
        frame.get_by_text(csv_path.name).first.wait_for(timeout=30000)
        num = frame.locator(".st-key-admin_team_count input")
        num.fill(str(team_count))
        num.press("Enter")
        time.sleep(1.5)
        got, text = self.press("admin", "admin_start")
        self.check(f"admin 명단 올리기({csv_path.name}, 팀 {team_count})", "승인", got, text)

    def unassigned_text(self):
        frame = self.app_frame(self.page_for("admin"))
        return frame.locator(".st-key-unassigned").inner_text()

    def final_check(self, roster):
        ctx = self.browser.new_context()
        page = ctx.new_page()
        self.login(page, "admin", self.admin_pw)
        frame = self.app_frame(page)
        frame.locator(".st-key-team_1").wait_for(timeout=30000)
        frame.locator(".st-key-unassigned").wait_for(timeout=30000)
        time.sleep(1)
        by_name = {s.name: s for s in roster}
        problems, t = [], 1
        while frame.locator(f".st-key-team_{t}").count():
            text = frame.locator(f".st-key-team_{t}").inner_text()
            members = [s for name, s in by_name.items() if f"{name}:" in text]
            problems += team_errors(t, members)
            t += 1
        left = frame.locator(".st-key-unassigned").inner_text()
        if any(f"{s.name}:" in left for s in roster):
            problems.append("팀이 없는 학생이 남아 있음")
        ctx.close()
        self.step += 1
        ok = not problems and t > 1
        self.failures += 0 if ok else 1
        print(f"{self.step:02d} 새 브라우저에서 확정한 팀 구성 검사(팀 {t - 1}개) | "
              f"{'일치' if ok else '불일치'} | {'; '.join(problems) or '모든 팀이 규칙을 지킴'}", flush=True)


def run(url, name, admin_pw, headed, debug_dir=None):
    sc = SCENARIOS[name]
    csv_path = FIXTURES / sc.csv_name
    roster = parse_roster(csv_path.read_bytes())
    names = {s.student_no: s.name for s in roster}
    print(f"== {name} 시나리오 ({url}) ==", flush=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        g = Grader(browser, url, admin_pw, debug_dir)
        g.upload(csv_path, sc.team_count)
        for a in sc.actions:
            who = a.actor
            label_who = "관리자" if who == "admin" else names.get(who, who)
            if a.kind == "apply":
                got, text = g.press(who, f"apply_{a.target}")
                g.check(f"{label_who} → 팀{a.target} 지원", a.expect, got, text)
            elif a.kind in ("yes", "no"):
                key = f"vote_{a.kind}_{a.target}"
                got, text = g.press(who, key)
                g.check(f"{label_who} → {names[a.target]}에 {'찬성' if a.kind == 'yes' else '거부'}",
                        a.expect, got, text)
            elif a.kind == "close":
                got, text = g.press("admin", "admin_close")
                g.check("관리자 모집 마감", a.expect, got, text)
                time.sleep(1)
                left = g.unassigned_text()
                missing = [n for n in a.expect_unassigned if n not in left]
                g.check("마감 뒤 unassigned에 기대한 이름이 있음", "있음", "없음" if missing else "있음",
                        f"빠진 이름: {missing}" if missing else f"{len(a.expect_unassigned)}명 모두 있음")
            elif a.kind == "assign_confirm":
                t0 = time.time()
                peek = []
                got, text = g.press("admin", "admin_assign", wait_ms=ASSIGN_WAIT_MS, peek=peek)
                print(f"   (AI 배정 단추를 누르고 2초 뒤 result: {peek[0]!r})", flush=True)
                status = g.app_frame(g.page_for("admin")).locator(".st-key-assign_status").inner_text()
                g.check(f"관리자 AI 배정({time.time() - t0:.0f}초)", "승인", got,
                        text + " / assign_status: " + " | ".join(status.splitlines()))
                got, text = g.press("admin", "admin_confirm")
                g.check("관리자 배정안 확정", a.expect, got, text)
        g.final_check(roster)
        browser.close()
    print(f"== {name}: 불일치 {g.failures}건 ==", flush=True)
    return g.failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--scenario", choices=[*SCENARIOS, "all"], default="all")
    ap.add_argument("--admin-password-env", default="ADMIN_PASSWORD")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--debug-dir", help="단추를 못 찾으면 화면 캡처를 저장할 폴더")
    args = ap.parse_args()
    admin_pw = os.environ.get(args.admin_password_env) or config.get_secret(args.admin_password_env)
    if not admin_pw:
        print(f"{args.admin_password_env} 없음")
        sys.exit(2)
    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    total = sum(run(args.url, n, admin_pw, args.headed, args.debug_dir) for n in names)
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
