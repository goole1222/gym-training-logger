"""
suggest.py — Progressive overload suggestion engine.

Plan C — weight-aware trend logic:

  Priority 1 — Adjusted consecutive decline (3+ records):
    For each step, allow 1 extra rep drop per 2.5 kg increase.
    If the adjusted drop is still > 0 for both consecutive steps → Deload.

  Priority 2 — Adjusted single-session drop (2+ records):
    Raw drop minus allowance (1 per 2.5 kg increase) ≥ 2 → Maintain.
    If weight increased, the rep drop is partially expected.

  Priority 3 — Standard progressive overload:
    reps ≥ 8 and sets ≥ 3  → increase by increment
    reps < 5               → maintain
    otherwise              → increase by small increment
"""

from statistics import mean
from typing import Optional


def _group_by_exercise(records: list[dict]) -> dict[str, list[dict]]:
    """
    Group record list into {exercise_name: [record, ...]} dict.
    Records within each group are in their original (chronological) order.
    """
    groups: dict[str, list[dict]] = {}
    for rec in records:
        key = rec["exercise"].lower()
        groups.setdefault(key, []).append(rec)
    return groups


def _suggest_for_exercise(name: str, recs: list[dict]) -> dict:
    """
    Given all records for one exercise (sorted oldest→newest),
    return a suggestion dict with keys: exercise, suggestion, reason.

    Rules (Plan C — trend-aware):
      Priority 1 — Consecutive decline (need 3+ records):
        last 2 sessions both had fewer reps than the one before
        → Deload: reduce weight by one increment

      Priority 2 — Significant single-session drop (need 2+ records):
        last session reps dropped ≥ 2 compared to previous session
        → Maintain: not ready to progress yet

      Priority 3 — Original progressive overload logic:
        reps ≥ 8 and sets ≥ 3  → increase by increment
        reps < 5               → maintain
        otherwise              → increase by small increment
    """
    last = recs[-1]
    last_weight: float = last["weight"]
    last_reps:   int   = last["reps"]
    last_sets:   int   = last["sets"]

    # Average weight of last 3 sessions (shown in the summary table)
    avg_weight = mean(r["weight"] for r in recs[-3:])

    # Increment size: lighter loads use smaller steps
    increment       = 1.25 if last_weight < 30 else 2.5
    small_increment = 1.25

    # ── Priority 1: Consecutive rep decline across last 3 sessions ──────────
    # Each step's raw rep drop is reduced by 1 per 2.5 kg increase (weight-adjusted).
    # Only trigger deload if the adjusted drop is still positive for BOTH steps.
    if len(recs) >= 3:
        r3, r2, r1 = recs[-3]["reps"], recs[-2]["reps"], recs[-1]["reps"]
        w3, w2, w1 = recs[-3]["weight"], recs[-2]["weight"], recs[-1]["weight"]

        allowance_step1 = int(max(0.0, w2 - w3) / 2.5)  # credit for step -3→-2
        allowance_step2 = int(max(0.0, w1 - w2) / 2.5)  # credit for step -2→-1

        adj_drop1 = (r3 - r2) - allowance_step1  # positive = real decline at step 1
        adj_drop2 = (r2 - r1) - allowance_step2  # positive = real decline at step 2

        if adj_drop1 > 0 and adj_drop2 > 0:
            deload_weight = max(0.0, last_weight - increment * 2)
            weight_note = (
                f" (weights: {w3:.2f}→{w2:.2f}→{w1:.2f} kg)"
                if not (w1 == w2 == w3) else ""
            )
            return {
                "exercise": name,
                "suggestion": f"Deload to {deload_weight:.2f} kg",
                "reason": (
                    f"Rep trend: {r3}→{r2}→{r1} reps{weight_note}. "
                    f"Two consecutive real declines — reduce weight to rebuild."
                ),
                "avg_weight_recent": round(avg_weight, 2),
            }

    # ── Priority 2: Big single-session drop (weight-adjusted, must be ≥ 2) ─
    # For every 2.5 kg increase, allow 1 extra rep drop before triggering.
    if len(recs) >= 2:
        prev_reps   = recs[-2]["reps"]
        prev_weight = recs[-2]["weight"]
        drop        = prev_reps - last_reps
        allowance   = int(max(0.0, last_weight - prev_weight) / 2.5)
        adj_drop    = drop - allowance

        if adj_drop >= 2:
            weight_note = (
                f", weight +{last_weight - prev_weight:.2f} kg (allowance {allowance} rep)"
                if allowance > 0 else ""
            )
            return {
                "exercise": name,
                "suggestion": "Maintain current weight",
                "reason": (
                    f"Last session: {last_sets}×{last_reps} reps @ {last_weight} kg "
                    f"(fell {drop} reps from previous {prev_reps}{weight_note}). "
                    "Consolidate before progressing."
                ),
                "avg_weight_recent": round(avg_weight, 2),
            }

    # ── Priority 3: Standard progressive overload ───────────────────────────
    if last_reps >= 8 and last_sets >= 3:
        next_weight = last_weight + increment
        suggestion  = f"Increase to {next_weight:.2f} kg"
        reason      = (
            f"Last session: {last_sets}×{last_reps} reps @ {last_weight} kg. "
            f"Target hit — add {increment} kg."
        )
    elif last_reps < 5:
        suggestion = "Maintain current weight"
        reason     = (
            f"Last session: {last_sets}×{last_reps} reps @ {last_weight} kg. "
            "Focus on reps and form before adding weight."
        )
    else:
        next_weight = last_weight + small_increment
        suggestion  = f"Increase to {next_weight:.2f} kg"
        reason      = (
            f"Last session: {last_sets}×{last_reps} reps @ {last_weight} kg. "
            f"Making progress — try adding {small_increment} kg."
        )

    return {
        "exercise": name,
        "suggestion": suggestion,
        "reason": reason,
        "avg_weight_recent": round(avg_weight, 2),
    }


def generate_suggestions(records: list[dict]) -> list[dict]:
    """
    Return a list of suggestion dicts for every exercise found in records.
    If records is empty, return an empty list.
    """
    if not records:
        return []

    groups = _group_by_exercise(records)
    suggestions = []
    for exercise_key, recs in sorted(groups.items()):
        # Use the display name from the most recent record (preserves original casing)
        display_name = recs[-1]["exercise"]
        result = _suggest_for_exercise(display_name, recs)
        suggestions.append(result)

    return suggestions


def print_suggestions(suggestions: list[dict]) -> None:
    """Pretty-print the suggestion list to stdout."""
    if not suggestions:
        print("  No records found. Add some training sessions first!")
        return

    print(f"\n  {'EXERCISE':<25} {'SUGGESTION':<30} {'3-SESSION AVG':>14}")
    print("  " + "-" * 72)
    for s in suggestions:
        print(
            f"  {s['exercise']:<25} {s['suggestion']:<30} {s['avg_weight_recent']:>12.2f} kg"
        )
        # Indent the reason line
        print(f"    → {s['reason']}")
        print()
