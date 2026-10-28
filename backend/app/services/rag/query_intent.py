"""规则驱动的 Query 意图分类 + 关键实体抽取（零额外 LLM 调用）。

P1「让系统更懂问题」的核心：识别用户在问「流程 / 定义 / 对比 / 计算 / 标准 /
是否」，并抽取金额、部门、时间等关键实体，驱动生成层差异化排版与检索槽位。
纯规则实现，不增加远程调用，不与 P0 时延优化冲突。
"""
from __future__ import annotations

import re

# 意图枚举
INTENT_PROCESS = "process"        # 流程 / 步骤 / 怎么办理
INTENT_DEFINITION = "definition"  # 是什么 / 定义
INTENT_COMPARE = "compare"        # 区别 / 对比 / 哪个
INTENT_CALCULATION = "calculation"  # 多少 / 比例 / 标准数值
INTENT_STANDARD = "standard"      # 标准 / 规定 / 要求 / 条件
INTENT_YESNO = "yesno"            # 是否 / 能不能 / 可以吗
INTENT_OTHER = "other"


def classify_intent(question: str) -> str:
    """按优先级规则分类问题意图（规则有序，先命中先返回）。"""
    q = (question or "").strip()
    if not q:
        return INTENT_OTHER
    # 对比类：区别/对比/哪个/差异
    if any(w in q for w in ("区别", "对比", "哪个", "差异", "比较", "分别", "不同")):
        return INTENT_COMPARE
    # 计算/标准数值类：金额/比例/计提/提取标准（先于「怎么」判断，「怎么提取」是问标准非流程）
    if any(w in q for w in (
        "多少", "多少钱", "比例", "怎么算", "计提", "提取标准", "计提标准", "提取", "金额", "费率",
        "多久", "几年", "几天", "年限", "最短时间", "最长时间",
    )):
        return INTENT_CALCULATION
    # 流程类：流程/怎么/如何/办理/步骤/程序/手续
    if any(w in q for w in ("流程", "怎么", "如何", "办理", "步骤", "程序", "手续", "申请")):
        return INTENT_PROCESS
    # 是否类：是否/能不能/可以吗/需要吗
    if any(w in q for w in ("是否", "能不能", "可以吗", "需要吗", "要不要", "可否")):
        return INTENT_YESNO
    # 标准/规定/要求/条件类
    if any(w in q for w in ("标准", "规定", "要求", "条件", "标准是", "标准为")):
        return INTENT_STANDARD
    # 定义类：什么是/定义/是什么/指什么
    if any(w in q for w in ("什么是", "定义", "是什么", "指什么", "指的是")):
        return INTENT_DEFINITION
    return INTENT_OTHER


_AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(万|亿)?\s*(美元|美金|人民币|元|欧元)?")
_DEPT_RE = re.compile(
    r"(人力资源部|财务部|总经理办公室|工程管理部|市场开发部|安全生产部|综合管理部|区域总部|总部|项目总经理部)"
)


def extract_entities(question: str) -> dict:
    """抽取关键实体：金额（含币种）、部门/机构。供槽位补充与检索提示。"""
    q = question or ""
    ents: dict = {}
    m = _AMOUNT_RE.search(q)
    if m:
        amt = m.group(1)
        unit = m.group(2) or ""
        cur = m.group(3) or ""
        ents["amount"] = f"{amt}{unit}{cur}".strip()
    depts = _DEPT_RE.findall(q)
    if depts:
        ents["departments"] = list(dict.fromkeys(depts))
    return ents


def query_hint(intent: str, entities: dict | None = None) -> str:
    """生成一段简短意图提示，注入生成层 system prompt，让排版贴合问题类型。"""
    hints = {
        INTENT_PROCESS: "这是一个「流程」类问题：按步骤/环节顺序组织，写清每个环节的负责方与前置条件。",
        INTENT_COMPARE: "这是一个「对比」类问题：优先用表格对比不同情形/对象的差异，再说明适用边界。",
        INTENT_CALCULATION: (
            "这是一个「计算/标准数值」类问题：先识别口径歧义，再列明原文中的每个输入值。"
            "凡属加总推导，必须在结论同一行写出可验算计算式并保证等式正确；"
            "若目标等级含子级（如 M5-1/M5-2），必须分别回答，不得合并猜测。"
        ),
        INTENT_STANDARD: "这是一个「标准/规定」类问题：先给结论性标准，再说明适用条件与例外情形。",
        INTENT_YESNO: "这是一个「是否」类问题：开篇直接给「是/否」结论，再说明条件与依据。",
        INTENT_DEFINITION: "这是一个「定义」类问题：先给一句话定义，再说明范围、口径与相关条款。",
        INTENT_OTHER: "",
    }
    hint = hints.get(intent, "")
    if entities and entities.get("amount"):
        hint += f" 注意问题中涉及金额「{entities['amount']}」，如与审批权限相关需明确币种与层级。"
    return hint.strip()
