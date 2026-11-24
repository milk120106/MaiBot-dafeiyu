"""月度預算設定不得誤傳上游 API。"""

from src.llm_models.openai_compat import split_openai_request_overrides


def test_monthly_budget_keys_are_stripped_from_request_body():
    overrides = split_openai_request_overrides({
        "monthly_requests": 100,
        "monthly_tokens": 1000,
        "monthly_budget_usd": 9,
        "monthly_budget_cny": 63,
        "temperature": 0.5,
    })
    assert overrides.extra_body == {"temperature": 0.5}
