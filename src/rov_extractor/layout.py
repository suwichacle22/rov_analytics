"""Turn what the draft bar shows (slots, left to right) into the 18-step sequence.

The RPL sequence is: ban 1-4, pick 1-6, ban 5-8, pick 7-10.
Ban n (1..8) maps to seq 1..4 and 11..14. Pick n (1..10) maps to seq 5..10 and 15..18.
A layout profile says which ban or pick number fills each screen slot per side.
"""
from __future__ import annotations

from typing import Any

BAN_SEQ = {1: 1, 2: 2, 3: 3, 4: 4, 5: 11, 6: 12, 7: 13, 8: 14}
PICK_SEQ = {1: 5, 2: 6, 3: 7, 4: 8, 5: 9, 6: 10, 7: 15, 8: 16, 9: 17, 10: 18}


def phase_of(seq: int) -> str:
    if seq <= 4:
        return "ban1"
    if seq <= 10:
        return "pick1"
    if seq <= 14:
        return "ban2"
    return "pick2"


def side_of_ban(ban_no: int, layout: dict[str, Any]) -> str:
    return "blue" if ban_no in layout["blue"]["banSlots"] else "red"


def side_of_pick(pick_no: int, layout: dict[str, Any]) -> str:
    return "blue" if pick_no in layout["blue"]["pickSlots"] else "red"


def build_sequence(layout: dict[str, Any], slots: dict[str, Any], blue_team: str, red_team: str) -> list[dict[str, Any]]:
    """slots = {blueBans: [..4], redBans: [..4], bluePicks: [{hero, player}..5], redPicks: [..5]}

    Ban entries are {hero, form} or a bare hero id string. Missing values are None.
    Returns the actions ordered by seq. Empty slots produce actions with hero None so the
    validator can name them.
    """
    actions: list[dict[str, Any]] = []
    for side, team in (("blue", blue_team), ("red", red_team)):
        ban_slots = layout[side]["banSlots"]
        pick_slots = layout[side]["pickSlots"]
        bans = slots.get(f"{side}Bans") or []
        picks = slots.get(f"{side}Picks") or []
        for slot_index, ban_no in enumerate(ban_slots):
            entry = bans[slot_index] if slot_index < len(bans) else None
            hero, form = _hero_form(entry)
            actions.append({
                "seq": BAN_SEQ[ban_no], "phase": phase_of(BAN_SEQ[ban_no]), "order": ban_no,
                "side": side, "team": team, "action": "ban", "slot": slot_index + 1,
                "hero": hero, "form": form,
            })
        for slot_index, pick_no in enumerate(pick_slots):
            entry = picks[slot_index] if slot_index < len(picks) else None
            hero, _ = _hero_form(entry)
            player = (entry or {}).get("player") if isinstance(entry, dict) else None
            actions.append({
                "seq": PICK_SEQ[pick_no], "phase": phase_of(PICK_SEQ[pick_no]), "order": pick_no,
                "side": side, "team": team, "action": "pick", "slot": slot_index + 1,
                "hero": hero, "preSwapPlayer": player or None,
            })
    actions.sort(key=lambda a: a["seq"])
    return actions


def _hero_form(entry: Any) -> tuple[str | None, str | None]:
    if entry is None:
        return None, None
    if isinstance(entry, str):
        return (entry or None), None
    hero = entry.get("hero") or None
    form = entry.get("form") or None
    return hero, form
