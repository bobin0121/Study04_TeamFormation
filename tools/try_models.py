# 생성: 2026-10-29 20:55 KST
"""오픈라우터 무료 모델 후보를 어려움 시나리오의 마감 직후 상태로 한 번씩 불러 본다.
키 값은 출력하지 않는다. 사용: python tools/try_models.py 모델1 모델2 ..."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from ai import AIError, build_messages, call_openrouter, call_with_deadline, parse_assignments  # noqa: E402
from rules import validate_plan  # noqa: E402
from tests.states import hard_after_close  # noqa: E402


def main(models):
    key = config.get_secret("OPENROUTER_API_KEY")
    if not key:
        print("OPENROUTER_API_KEY 없음")
        return
    teams, unassigned = hard_after_close()
    messages = build_messages(teams, unassigned)
    current = {m.student_no: t for t, ms in teams.items() for m in ms}
    print(f"시험 시각: {time.strftime('%Y-%m-%d %H:%M')}")
    for model in models:
        start = time.monotonic()
        try:
            text = call_with_deadline(lambda: call_openrouter(model, messages, key), 120, lambda e: None)
            pairs = parse_assignments(text)
            if pairs is None:
                result = "실패: 배정안을 JSON으로 읽을 수 없음"
            else:
                pairs = [(no, t) for no, t in pairs if current.get(no) != t]
                errors = validate_plan(teams, unassigned, pairs)
                result = "성공" if not errors else f"실패: 검사 {len(errors)}건 - {errors[0]}"
        except AIError as e:
            result = f"실패: {e}"
        print(f"{model} | {time.monotonic() - start:.0f}초 | {result}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
