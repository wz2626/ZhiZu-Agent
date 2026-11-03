"""Fixed practice policy. No model, network client or cloud configuration."""

import re

_TEMPLATES = {
    "deposit": ("deposit_refund", "我确认返还押金", "元"),
    "maintenance": ("repair_cost_share", "我确认承担维修费用", "%"),
    "early_termination": ("termination_fee", "我确认提前退租违约金为", "元"),
}
_ACCEPTANCE = {
    scenario: re.compile(
        re.escape("【模拟房东】" + prefix) + r"(?P<amount>-?\d+(?:\.\d+)?)" + re.escape(unit)
        + r"[。]?(?:依据LAW-\d{3}(?:[、,，]LAW-\d{3})*。?)?"
    ) for scenario, (_, prefix, unit) in _TEMPLATES.items()
}
OFFERS = {"deposit": (1000, 1500, 2000), "maintenance": (50, 75, 100), "early_termination": (1000, 500, 0)}
MISSING_FACTS = {
    "deposit": ["核对押金收据、扣减明细与交接记录。"],
    "maintenance": ["核对损坏原因、报修记录与维修费用凭证。"],
    "early_termination": ["核对通知日期、费用约定与房屋交接安排。"],
}


def scenario_landlord_responder(state) -> str:
    amount = OFFERS[state.scenario][min(state.round_count, len(OFFERS[state.scenario]) - 1)]
    _, prefix, unit = _TEMPLATES[state.scenario]
    return f"【模拟房东】{prefix}{amount}{unit}。"


def final_offer_round(scenario):
    return len(OFFERS[scenario])
