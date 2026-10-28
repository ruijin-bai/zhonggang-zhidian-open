"""Intent and entity rules must stay deterministic across common question forms."""
from app.services.rag.query_intent import classify_intent, extract_entities, query_hint


def test_intent_priority_matrix():
    cases = {
        "借调需要办理哪些手续？": "process",
        "安全费用提取比例是多少？": "calculation",
        "正式员工和劳务派遣有什么区别？": "compare",
        "什么是境外项目属地化管理？": "definition",
        "这项付款是否需要总部审批？": "yesno",
        "船机设备安全管理有哪些要求？": "standard",
        "请介绍考勤制度": "other",
    }
    assert {question: classify_intent(question) for question in cases} == cases


def test_amount_and_department_entities_are_preserved_not_inferred():
    entities = extract_entities("50万美元由区域总部还是财务部审批？")
    assert entities == {"amount": "50万美元", "departments": ["区域总部", "财务部"]}
    hint = query_hint("yesno", entities)
    assert "50万美元" in hint
    assert "币种" in hint

