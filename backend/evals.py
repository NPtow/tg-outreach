from backend.conversation_agent import generate_structured_reply, guardrail_check


def run_local_eval_cases(cases: list[dict]) -> dict:
    failures = []
    for case in cases:
        reply = generate_structured_reply(None, history=case.get("history", []), model="local-eval-agent")
        guardrail = guardrail_check(reply, scheduled_meeting_exists=False)
        case_failures = []
        if case.get("expected_action") and reply["action"] != case["expected_action"]:
            case_failures.append(f"expected action {case['expected_action']}, got {reply['action']}")
        text_l = (reply.get("reply_text") or "").lower()
        for token in case.get("must_include", []):
            if token.lower() not in text_l:
                case_failures.append(f"missing required text: {token}")
        for token in case.get("must_not_include", []):
            if token.lower() in text_l:
                case_failures.append(f"contains banned text: {token}")
        if not guardrail["safe_to_send"]:
            case_failures.append(f"guardrail failed: {','.join(guardrail['issues'])}")
        if case_failures:
            failures.append({"id": case.get("id"), "failures": case_failures, "reply": reply})

    total = len(cases)
    failed = len(failures)
    passed = total - failed
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "score": round(passed / total, 3) if total else 0.0,
        "failures": failures,
    }


DEFAULT_EVAL_CASES = [
    {
        "id": "booking_intent_ru",
        "history": [{"role": "user", "text": "Да, давайте созвонимся"}],
        "expected_action": "book_meeting",
        "must_not_include": ["[[BOOK_MEETING]]"],
    },
    {
        "id": "research_context_ru",
        "history": [{"role": "user", "text": "Что вы исследуете?"}],
        "expected_action": "send_reply",
        "must_include": ["исслед"],
    },
    {
        "id": "stop_request_ru",
        "history": [{"role": "user", "text": "Не пишите мне больше, стоп"}],
        "expected_action": "do_not_contact",
    },
]
