"""Closed vocabulary shared by deterministic rule and case workflows."""
from typing import Literal

BusinessScenario = Literal[
    "contract_change",
    "payment",
    "procurement",
    "safety",
    "employment",
]
