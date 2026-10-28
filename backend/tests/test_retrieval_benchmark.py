from app.services.eval.retrieval_benchmark import load_retrieval_benchmark


def test_retrieval_smoke_suite_is_distinct_and_has_100_questions():
    cases = load_retrieval_benchmark()
    assert len(cases) == 100
    assert all(case.get("question") and case.get("expect") for case in cases)
