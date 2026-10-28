from scripts.verify_model_runtime import (
    _SYNTHETIC_LLM_MAX_TOKENS,
    _provider_check,
    _safe_error,
)


class MockLike:
    kind = "mock"


class RealLike:
    kind = "openai_compat"


def test_runtime_verifier_fails_closed_for_mock_by_default():
    assert _provider_check(MockLike(), allow_mock=False) == (False, "mock")
    assert _provider_check(MockLike(), allow_mock=True) == (True, "mock")
    assert _provider_check(RealLike(), allow_mock=False) == (True, "openai_compat")
    assert _provider_check(None, allow_mock=False) == (False, "unconfigured")


def test_runtime_verifier_never_serializes_provider_error_details():
    secret = "sk-sensitive-value"
    error_code = _safe_error(RuntimeError(f"provider failed with {secret}"))
    assert error_code == "RuntimeError"
    assert secret not in error_code


def test_runtime_verifier_allows_reasoning_model_to_reach_final_answer():
    assert _SYNTHETIC_LLM_MAX_TOKENS >= 256
