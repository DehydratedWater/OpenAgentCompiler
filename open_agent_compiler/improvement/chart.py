"""ASCII charts for visualising loop progress.

Used by `oac improve` output and the examples. Pure-stdlib renderer —
no rich/textual dependency.
"""

from __future__ import annotations

from open_agent_compiler.improvement.loop import LoopResult
from open_agent_compiler.improvement.scoring import aggregate_score
from open_agent_compiler.improvement.criteria import OptimisationCriterion


def _bar(value: float, width: int = 30, *, ch: str = "█") -> str:
    value = max(0.0, min(1.0, value))
    fill = int(round(value * width))
    return ch * fill + "·" * (width - fill)


def render_round_progression(
    result: LoopResult, criterion: OptimisationCriterion,
    *, width: int = 30,
) -> str:
    """One bar per round showing best aggregate score seen.

    Output:
      round 0: ███████████···················  0.633  (baseline)
      round 1: ██████████████████████████████  1.000  (+0.367 from llm-prompt-rewriter)
      round 2: ██████████████████████████████  1.000  (no change)
    """
    lines = ["", "Score progression (best per round):"]
    seen_best = 0.0
    for round_idx, round_out in enumerate(result.rounds):
        if not round_out.candidates:
            lines.append(
                f"  round {round_idx}: {_bar(seen_best, width)} "
                f"{seen_best:.3f}  (no new candidates)"
            )
            continue
        scores = [
            (aggregate_score(criterion, c.metrics), c.author) for c in round_out.candidates
        ]
        scores.sort(reverse=True)
        round_best, round_author = scores[0]
        delta = round_best - seen_best
        if round_best > seen_best:
            note = f"(+{delta:.3f} from {round_author})"
            seen_best = round_best
        else:
            note = "(no improvement)"
        lines.append(
            f"  round {round_idx}: {_bar(round_best, width)}"
            f"  {round_best:.3f}  {note}"
        )
    if result.winners:
        winner = result.winners[0]
        winner_score = aggregate_score(criterion, winner.metrics)
        lines.append("")
        lines.append(
            f"Final winner: {winner.author!r} agg={winner_score:.3f}"
            f" (hash={winner.content_hash[:8]}…)"
        )
        lines.append(f"  metrics: {winner.metrics}")
    return "\n".join(lines)


def render_per_candidate_table(
    result: LoopResult, criterion: OptimisationCriterion,
    *, max_rows: int = 20,
) -> str:
    """All candidates across all rounds, sorted by aggregate score."""
    all_candidates = []
    for round_idx, round_out in enumerate(result.rounds):
        for c in round_out.candidates:
            all_candidates.append((round_idx, c))
    if not all_candidates:
        return "no candidates"

    rows = [
        (round_idx, c, aggregate_score(criterion, c.metrics))
        for round_idx, c in all_candidates
    ]
    rows.sort(key=lambda r: r[2], reverse=True)
    rows = rows[:max_rows]

    lines = ["", "Per-candidate scores (top {}):".format(len(rows))]
    lines.append(
        f"  {'agg':>5s}  {'rnd':>3s}  {'hash':>8s}  author"
    )
    for round_idx, c, agg in rows:
        lines.append(
            f"  {agg:>5.3f}  {round_idx:>3d}  {c.content_hash[:8]}  {c.author}"
        )
    return "\n".join(lines)
