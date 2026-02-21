#!/usr/bin/env python3
"""Multi-criteria Pareto analysis with marginal gain sweet spot detection.

Usage:
  # Flat input (stdin or file)
  echo '[{"name":"A","cost":10,"perf":90}]' | pareto-decide -m cost -M perf
  pareto-decide items.csv -m cost -M perf,ram -f markdown

  # With marginal gain analysis (--sort-by enables sweet spots)
  pareto-decide items.json -m cost -M perf,ram --sort-by cost

  # Structured input (criteria/weights embedded in JSON)
  pareto-decide specs.json
  pareto-decide specs.json --weights "ram_gb:0.3,mem_bw_gbps:0.35"

Input formats:
  JSON array:   [{"name":"A", "x":1, "y":2}, ...]
  JSON object:  {"criteria":[...], "configs":[...], "cost_field":"price", ...}
  CSV:          header row + data rows

Output formats: json (default), table, markdown, csv
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
from typing import Any


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------


def parse_criteria_arg(criteria_str: str) -> list[dict[str, str]]:
    """Parse "field:max,field:min" format."""
    result: list[dict[str, str]] = []
    for part in criteria_str.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        name, direction = part.rsplit(":", 1)
        d = direction.strip().lower()
        if d in ("max", "maximize"):
            d = "maximize"
        elif d in ("min", "minimize"):
            d = "minimize"
        else:
            print(f"Warning: unknown direction '{d}' for {name}", file=sys.stderr)
            d = "maximize"
        result.append({"name": name.strip(), "direction": d})
    return result


def parse_weights_arg(weights_str: str) -> dict[str, float]:
    """Parse "field:weight,field:weight" format."""
    result: dict[str, float] = {}
    for pair in weights_str.split(","):
        pair = pair.strip()
        if ":" in pair:
            k, v = pair.rsplit(":", 1)
            result[k.strip()] = float(v.strip())
    return result


def read_csv_input(text: str) -> list[dict[str, Any]]:
    """Parse CSV with auto numeric conversion."""
    reader = csv.DictReader(io.StringIO(text))
    items: list[dict[str, Any]] = []
    for row in reader:
        item: dict[str, Any] = {}
        for k, v in row.items():
            if k is None:
                continue
            try:
                item[k] = int(v)
            except ValueError:
                try:
                    item[k] = float(v)
                except ValueError:
                    item[k] = v
        items.append(item)
    return items


def load_input(
    file_path: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Load input. Returns (configs, structured_meta_or_None)."""
    if file_path is None or file_path == "-":
        text = sys.stdin.read()
    else:
        with open(file_path) as f:
            text = f.read()

    text = text.strip()
    if not text:
        return [], None

    if file_path and file_path.endswith(".csv"):
        return read_csv_input(text), None

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return read_csv_input(text), None

    if isinstance(data, list):
        return data, None

    if isinstance(data, dict) and "configs" in data:
        return data["configs"], data

    print(
        "Error: JSON must be an array or object with 'configs' key",
        file=sys.stderr,
    )
    sys.exit(1)


def build_criteria(
    structured_meta: dict[str, Any] | None,
    maximize: list[str],
    minimize: list[str],
    criteria_arg: list[dict[str, str]],
    weight_overrides: dict[str, float],
) -> list[dict[str, Any]]:
    """Build unified criteria list."""
    criteria: list[dict[str, Any]] = []

    if structured_meta and "criteria" in structured_meta:
        for cd in structured_meta["criteria"]:
            name = cd["name"]
            w = weight_overrides.get(name, cd.get("weight", 1.0))
            criteria.append(
                {
                    "name": name,
                    "direction": cd.get("direction", "maximize"),
                    "weight": w,
                }
            )
    else:
        seen: set[str] = set()
        for c in criteria_arg:
            criteria.append(
                {
                    "name": c["name"],
                    "direction": c["direction"],
                    "weight": weight_overrides.get(c["name"], 1.0),
                }
            )
            seen.add(c["name"])
        for name in maximize:
            if name not in seen:
                criteria.append(
                    {
                        "name": name,
                        "direction": "maximize",
                        "weight": weight_overrides.get(name, 1.0),
                    }
                )
                seen.add(name)
        for name in minimize:
            if name not in seen:
                criteria.append(
                    {
                        "name": name,
                        "direction": "minimize",
                        "weight": weight_overrides.get(name, 1.0),
                    }
                )
                seen.add(name)

    if not criteria:
        print(
            "Error: no criteria specified. Use -M/-m/-c or structured input.",
            file=sys.stderr,
        )
        sys.exit(1)

    return criteria


# ---------------------------------------------------------------------------
# Core: Pareto dominance
# ---------------------------------------------------------------------------


def is_dominated(
    a: dict[str, Any], b: dict[str, Any], criteria: list[dict[str, Any]]
) -> bool:
    """True if b dominates a (b >= a on all criteria, b > a on at least one)."""
    any_strictly_better = False
    for c in criteria:
        va = a.get(c["name"], 0)
        vb = b.get(c["name"], 0)
        if c["direction"] == "maximize":
            if vb < va:
                return False
            if vb > va:
                any_strictly_better = True
        else:
            if vb > va:
                return False
            if vb < va:
                any_strictly_better = True
    return any_strictly_better


def compute_pareto_front(
    configs: list[dict[str, Any]], criteria: list[dict[str, Any]]
) -> list[int]:
    """Indices of non-dominated items."""
    n = len(configs)
    front: list[int] = []
    for i in range(n):
        if not any(
            j != i and is_dominated(configs[i], configs[j], criteria) for j in range(n)
        ):
            front.append(i)
    return front


def compute_dominated(
    configs: list[dict[str, Any]],
    criteria: list[dict[str, Any]],
    front: list[int],
    name_field: str,
) -> list[dict[str, Any]]:
    """For each dominated item, find dominators with reasons."""
    front_set = set(front)
    result: list[dict[str, Any]] = []

    for i in range(len(configs)):
        if i in front_set:
            continue
        dominators: list[dict[str, Any]] = []
        for j in front:
            if not is_dominated(configs[i], configs[j], criteria):
                continue
            advantages = []
            for c in criteria:
                vi = configs[i].get(c["name"], 0)
                vj = configs[j].get(c["name"], 0)
                if (c["direction"] == "maximize" and vj > vi) or (
                    c["direction"] == "minimize" and vj < vi
                ):
                    advantages.append(f"{c['name']}: {vi}->{vj}")
            dominators.append(
                {
                    "index": j,
                    "name": configs[j].get(name_field, f"#{j}"),
                    "advantages": advantages,
                }
            )
            if len(dominators) >= 3:
                break
        result.append(
            {
                "index": i,
                "name": configs[i].get(name_field, f"#{i}"),
                "dominated_by": dominators,
            }
        )
    return result


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def _normalize_value(
    value: float, min_val: float, max_val: float, direction: str
) -> float:
    """Normalize to 0-1 range. For minimize, invert so higher = better."""
    if max_val == min_val:
        return 0.5
    norm = (value - min_val) / (max_val - min_val)
    if direction == "minimize":
        norm = 1.0 - norm
    return norm


def _compute_composite_score(
    config: dict[str, Any],
    criteria: list[dict[str, Any]],
    min_max: dict[str, tuple[float, float]],
) -> float:
    """Weighted composite score (0-1) using normalized criterion values."""
    total_weight = 0.0
    weighted_sum = 0.0
    for c in criteria:
        mn, mx = min_max[c["name"]]
        val = config.get(c["name"], 0)
        norm = _normalize_value(val, mn, mx, c["direction"])
        w = c.get("weight", 1.0)
        weighted_sum += w * norm
        total_weight += w
    return round(weighted_sum / total_weight, 4) if total_weight > 0 else 0.0


def _build_min_max(
    configs: list[dict[str, Any]], criteria: list[dict[str, Any]]
) -> dict[str, tuple[float, float]]:
    """Compute min/max per criterion across all configs."""
    mm: dict[str, tuple[float, float]] = {}
    for c in criteria:
        vals = [cfg.get(c["name"], 0) for cfg in configs]
        mm[c["name"]] = (min(vals), max(vals))
    return mm


# ---------------------------------------------------------------------------
# Marginal gain analysis (requires --sort-by)
# ---------------------------------------------------------------------------


def _metric_ratio(v_from: float, v_to: float, direction: str) -> float:
    """Improvement ratio respecting direction."""
    if direction == "maximize":
        return v_to / v_from if v_from != 0 else (float("inf") if v_to > 0 else 1.0)
    return v_from / v_to if v_to != 0 else (float("inf") if v_from > 0 else 1.0)


def compute_marginal_gains(
    cfg_from: dict[str, Any],
    cfg_to: dict[str, Any],
    criteria: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Per-criterion gain ratios between two configs."""
    gains: list[dict[str, Any]] = []
    for c in criteria:
        name = c["name"]
        v_from = cfg_from.get(name, 0)
        v_to = cfg_to.get(name, 0)
        ratio = v_to / v_from if v_from != 0 else (float("inf") if v_to != 0 else 1.0)
        gains.append(
            {"field": name, "from": v_from, "to": v_to, "ratio": round(ratio, 3)}
        )
    return gains


def compute_gain_score(
    cfg_from: dict[str, Any],
    cfg_to: dict[str, Any],
    criteria: list[dict[str, Any]],
    sort_field: str,
    sort_direction: str,
) -> float:
    """Weighted performance gain / sort-axis change ratio.

    > 1.0 means proportionally more improvement than sort-axis increase.
    """
    s_from = cfg_from.get(sort_field, 0)
    s_to = cfg_to.get(sort_field, 0)
    if s_from == 0:
        return 0.0

    if sort_direction == "asc":
        if s_to <= s_from:
            return 0.0
        sort_ratio = s_to / s_from
    else:
        if s_to >= s_from:
            return 0.0
        sort_ratio = s_from / s_to

    weighted_gain = 0.0
    total_weight = 0.0
    for c in criteria:
        if c["name"] == sort_field:
            continue
        v_from = cfg_from.get(c["name"], 0)
        v_to = cfg_to.get(c["name"], 0)
        weighted_gain += c["weight"] * _metric_ratio(v_from, v_to, c["direction"])
        total_weight += c["weight"]

    if total_weight > 0:
        weighted_gain /= total_weight

    return float(round(weighted_gain / sort_ratio, 4))


def detect_sweet_spots(
    configs: list[dict[str, Any]],
    criteria: list[dict[str, Any]],
    sort_field: str,
    sort_direction: str,
    threshold: float,
    name_field: str,
) -> list[dict[str, Any]]:
    """Items where gain_score is disproportionately high along the sort axis."""
    reverse = sort_direction == "desc"
    sorted_indices = sorted(
        range(len(configs)),
        key=lambda i: configs[i].get(sort_field, 0),
        reverse=reverse,
    )

    sort_vals = [configs[i].get(sort_field, 0) for i in sorted_indices]
    if len(sort_vals) < 2:
        return []
    sort_range = max(sort_vals) - min(sort_vals)
    min_gap = sort_range * 0.03 if sort_range > 0 else 0

    sweet_spots: list[dict[str, Any]] = []

    for pos in range(1, len(sorted_indices)):
        idx = sorted_indices[pos]
        cfg = configs[idx]
        best_gain = 0.0
        best_from = sorted_indices[0]

        for prev_pos in range(pos):
            prev_idx = sorted_indices[prev_pos]
            prev_cfg = configs[prev_idx]
            gap = abs(cfg.get(sort_field, 0) - prev_cfg.get(sort_field, 0))
            if gap < min_gap:
                continue
            score = compute_gain_score(
                prev_cfg, cfg, criteria, sort_field, sort_direction
            )
            if score > best_gain:
                best_gain = score
                best_from = prev_idx

        if best_gain >= threshold:
            gains = compute_marginal_gains(configs[best_from], cfg, criteria)
            top_gains = sorted(gains, key=lambda g: g["ratio"], reverse=True)[:3]
            reason_parts = [
                f"{g['field']}:{g['ratio']:.1f}x" for g in top_gains if g["ratio"] > 1.1
            ]
            sweet_spots.append(
                {
                    "config_index": idx,
                    "name": cfg.get(name_field, f"#{idx}"),
                    "sort_value": cfg.get(sort_field, 0),
                    "gain_score": best_gain,
                    "compared_to_index": best_from,
                    "compared_to_name": configs[best_from].get(
                        name_field, f"#{best_from}"
                    ),
                    "reason": f"gain_score {best_gain:.2f} — {', '.join(reason_parts)}",
                    "marginal_gains": gains,
                }
            )

    sweet_spots.sort(key=lambda s: s["gain_score"], reverse=True)
    return sweet_spots


def detect_traps(
    configs: list[dict[str, Any]],
    criteria: list[dict[str, Any]],
    sort_field: str | None,
    tolerance: float,
    name_field: str,
) -> list[dict[str, Any]]:
    """Trap items: close on sort axis but strictly worse on other criteria.

    Without sort_field: pure domination only.
    """
    traps: list[dict[str, Any]] = []
    found: set[int] = set()

    for i in range(len(configs)):
        if i in found:
            continue
        for j in range(len(configs)):
            if i == j:
                continue

            # Proximity check on sort axis
            if sort_field:
                vi_s = configs[i].get(sort_field, 0)
                vj_s = configs[j].get(sort_field, 0)
                ref = max(abs(vi_s), abs(vj_s), 1e-9)
                if abs(vi_s - vj_s) / ref > tolerance:
                    continue

            compare_criteria = (
                [c for c in criteria if c["name"] != sort_field]
                if sort_field
                else criteria
            )

            j_better = 0
            i_better = 0
            details: list[str] = []
            for c in compare_criteria:
                ci = configs[i].get(c["name"], 0)
                cj = configs[j].get(c["name"], 0)
                ref = max(abs(ci), abs(cj), 1e-9)
                if c["direction"] == "maximize":
                    if (cj - ci) / ref > 0.1:
                        j_better += 1
                        details.append(f"{c['name']}: {ci}->{cj}")
                    elif (ci - cj) / ref > 0.1:
                        i_better += 1
                elif (ci - cj) / ref > 0.1:
                    j_better += 1
                    details.append(f"{c['name']}: {ci}->{cj}")
                elif (cj - ci) / ref > 0.1:
                    i_better += 1

            if j_better >= 2 and i_better == 0:
                sort_info = ""
                if sort_field:
                    vi_s = configs[i].get(sort_field, 0)
                    vj_s = configs[j].get(sort_field, 0)
                    sort_info = f" ({sort_field} diff: {abs(vi_s - vj_s):.4g})"
                traps.append(
                    {
                        "index": i,
                        "name": configs[i].get(name_field, f"#{i}"),
                        "dominated_by_index": j,
                        "dominated_by_name": configs[j].get(name_field, f"#{j}"),
                        "reason": f"Similar{sort_info}, but worse: {'; '.join(details)}",
                    }
                )
                found.add(i)
                break

    return traps


def compute_tier_transitions(
    configs: list[dict[str, Any]],
    criteria: list[dict[str, Any]],
    sort_field: str,
    sort_direction: str,
    name_field: str,
) -> list[dict[str, Any]]:
    """Sequential transitions along sort axis, finding disproportionate jumps."""
    reverse = sort_direction == "desc"
    sorted_indices = sorted(
        range(len(configs)),
        key=lambda i: configs[i].get(sort_field, 0),
        reverse=reverse,
    )

    sort_vals = [configs[i].get(sort_field, 0) for i in sorted_indices]
    if len(sort_vals) < 2:
        return []
    sort_range = max(sort_vals) - min(sort_vals)
    if sort_range == 0:
        return []

    # Dynamic bucket size
    target_buckets = min(15, len(sort_vals))
    bucket_size = sort_range / target_buckets if target_buckets > 0 else 1

    seen_buckets: set[int] = set()
    representative: list[int] = []
    for idx in sorted_indices:
        val = configs[idx].get(sort_field, 0)
        bucket = int(val / bucket_size) if bucket_size > 0 else 0
        if bucket not in seen_buckets:
            seen_buckets.add(bucket)
            representative.append(idx)

    min_delta = sort_range * 0.03
    transitions: list[dict[str, Any]] = []

    for pos in range(1, len(representative)):
        from_idx = representative[pos - 1]
        to_idx = representative[pos]
        s_from = configs[from_idx].get(sort_field, 0)
        s_to = configs[to_idx].get(sort_field, 0)
        delta = abs(s_to - s_from)
        if delta < min_delta:
            continue

        sort_ratio = s_to / s_from if s_from != 0 else 0.0
        gains = compute_marginal_gains(configs[from_idx], configs[to_idx], criteria)
        key_jumps = [
            f"{g['field']}:{g['ratio']:.1f}x"
            for g in gains
            if g["ratio"] > 1.2 or (0 < g["ratio"] < 0.83)
        ]
        score = compute_gain_score(
            configs[from_idx], configs[to_idx], criteria, sort_field, sort_direction
        )
        transitions.append(
            {
                "from_idx": from_idx,
                "to_idx": to_idx,
                "from_name": configs[from_idx].get(name_field, f"#{from_idx}"),
                "to_name": configs[to_idx].get(name_field, f"#{to_idx}"),
                "delta": round(delta, 4),
                "sort_ratio": round(sort_ratio, 3),
                "key_jumps": key_jumps,
                "gain_score": score,
            }
        )

    return transitions


# ---------------------------------------------------------------------------
# Front trade-offs, auto-detect, weighted ranking, segment bests
# ---------------------------------------------------------------------------


def compute_front_tradeoffs(
    configs: list[dict[str, Any]],
    criteria: list[dict[str, Any]],
    front: list[int],
    name_field: str,
) -> list[dict[str, Any]]:
    """Per-item strengths/weaknesses + pairwise trade-off summary for front items."""
    if len(front) < 2:
        return []

    min_max = _build_min_max(configs, criteria)
    items: list[dict[str, Any]] = []

    for idx in front:
        cfg = configs[idx]
        strengths: list[str] = []
        weaknesses: list[str] = []
        for c in criteria:
            mn, mx = min_max[c["name"]]
            norm = _normalize_value(cfg.get(c["name"], 0), mn, mx, c["direction"])
            if norm >= 0.8:
                strengths.append(c["name"])
            elif norm <= 0.2:
                weaknesses.append(c["name"])
        items.append(
            {
                "index": idx,
                "name": cfg.get(name_field, f"#{idx}"),
                "strengths": strengths,
                "weaknesses": weaknesses,
            }
        )

    # Pairwise trade-offs
    tradeoffs: list[dict[str, Any]] = []
    for i_pos in range(len(front)):
        for j_pos in range(i_pos + 1, len(front)):
            a_idx, b_idx = front[i_pos], front[j_pos]
            a, b = configs[a_idx], configs[b_idx]
            a_better: list[str] = []
            b_better: list[str] = []
            for c in criteria:
                va, vb = a.get(c["name"], 0), b.get(c["name"], 0)
                if c["direction"] == "maximize":
                    if va > vb:
                        a_better.append(c["name"])
                    elif vb > va:
                        b_better.append(c["name"])
                elif va < vb:
                    a_better.append(c["name"])
                elif vb < va:
                    b_better.append(c["name"])
            if a_better or b_better:
                tradeoffs.append(
                    {
                        "a": a.get(name_field, f"#{a_idx}"),
                        "b": b.get(name_field, f"#{b_idx}"),
                        "a_better_at": a_better,
                        "b_better_at": b_better,
                    }
                )

    return [{"items": items, "pairwise": tradeoffs}]


def _auto_detect_sort_field(
    criteria: list[dict[str, Any]],
) -> tuple[str | None, str]:
    """If exactly one minimize criterion, use it as sort axis (asc)."""
    minimize_criteria = [c for c in criteria if c["direction"] == "minimize"]
    if len(minimize_criteria) == 1:
        return minimize_criteria[0]["name"], "asc"
    return None, "asc"


def compute_weighted_ranking(
    configs: list[dict[str, Any]],
    criteria: list[dict[str, Any]],
    name_field: str,
) -> list[dict[str, Any]]:
    """Rank all items by composite score. Fallback when no sort axis."""
    min_max = _build_min_max(configs, criteria)
    ranked: list[dict[str, Any]] = []
    for i, cfg in enumerate(configs):
        score = _compute_composite_score(cfg, criteria, min_max)
        ranked.append(
            {
                "index": i,
                "name": cfg.get(name_field, f"#{i}"),
                "composite_score": score,
            }
        )
    ranked.sort(key=lambda r: r["composite_score"], reverse=True)
    for rank, item in enumerate(ranked, 1):
        item["rank"] = rank
    return ranked


def compute_segment_bests(
    configs: list[dict[str, Any]],
    criteria: list[dict[str, Any]],
    sort_field: str,
    sort_direction: str,
    name_field: str,
    num_segments: int | None = None,
) -> list[dict[str, Any]]:
    """Split sort axis into equal-width segments, find best per segment."""
    vals = [cfg.get(sort_field, 0) for cfg in configs]
    lo, hi = min(vals), max(vals)
    if lo == hi:
        return []

    n = len(configs)
    if num_segments is None:
        num_segments = max(3, min(8, int(math.sqrt(n))))

    width = (hi - lo) / num_segments
    min_max = _build_min_max(configs, criteria)
    non_sort_criteria = [c for c in criteria if c["name"] != sort_field]

    segments: list[dict[str, Any]] = []
    for seg_idx in range(num_segments):
        seg_lo = lo + seg_idx * width
        seg_hi = seg_lo + width
        # Include upper bound for last segment
        indices = [
            i
            for i, v in enumerate(vals)
            if (seg_lo <= v < seg_hi) or (seg_idx == num_segments - 1 and v == seg_hi)
        ]
        if not indices:
            continue

        # Local pareto within segment
        local_configs = [configs[i] for i in indices]
        local_front_local = (
            compute_pareto_front(local_configs, non_sort_criteria)
            if non_sort_criteria
            else list(range(len(indices)))
        )
        local_front_global = [indices[li] for li in local_front_local]

        # Best by composite score among local front
        best_idx = max(
            local_front_global,
            key=lambda i: _compute_composite_score(
                configs[i], non_sort_criteria or criteria, min_max
            ),
        )
        best_score = _compute_composite_score(
            configs[best_idx], non_sort_criteria or criteria, min_max
        )

        alternatives = [
            configs[i].get(name_field, f"#{i}")
            for i in local_front_global
            if i != best_idx
        ]

        seg_label = f"{seg_lo:.4g}-{seg_hi:.4g}"
        segments.append(
            {
                "range": seg_label,
                "range_low": round(seg_lo, 4),
                "range_high": round(seg_hi, 4),
                "best_index": best_idx,
                "best": configs[best_idx].get(name_field, f"#{best_idx}"),
                "composite_score": best_score,
                "alternatives": alternatives,
                "item_count": len(indices),
                "reason": f"Best composite score ({best_score:.2f}) in {sort_field} range {seg_label}",
            }
        )

    return segments


# ---------------------------------------------------------------------------
# Analysis pipeline
# ---------------------------------------------------------------------------


def analyze(
    configs: list[dict[str, Any]],
    criteria: list[dict[str, Any]],
    sort_field: str | None = None,
    sort_direction: str = "asc",
    threshold: float = 0.85,
    tolerance: float = 0.05,
    name_field: str = "name",
) -> dict[str, Any]:
    """Run full analysis pipeline.

    1. Pareto front + dominated (always)
    2. Front trade-offs (front >= 2)
    3. Auto-detect sort_field if not provided
    4. With sort_field: sweet_spots + traps + transitions + segment_bests
    5. Without sort_field: traps + weighted_ranking
    """
    for i, cfg in enumerate(configs):
        if name_field not in cfg:
            cfg[name_field] = f"#{i}"

    front = compute_pareto_front(configs, criteria)
    dominated = compute_dominated(configs, criteria, front, name_field)

    result: dict[str, Any] = {
        "summary": {
            "total": len(configs),
            "pareto_count": len(front),
            "pareto_ratio": round(len(front) / len(configs), 3) if configs else 0,
        },
        "pareto_front": front,
        "pareto_front_names": [configs[i].get(name_field, f"#{i}") for i in front],
        "dominated": dominated,
        "criteria_used": criteria,
    }

    # Front trade-offs (always when front >= 2)
    if len(front) >= 2:
        ft = compute_front_tradeoffs(configs, criteria, front, name_field)
        result["front_tradeoffs"] = ft

    # Auto-detect sort_field
    sort_field_auto = False
    if not sort_field:
        detected, detected_dir = _auto_detect_sort_field(criteria)
        if detected:
            sort_field = detected
            sort_direction = detected_dir
            sort_field_auto = True
            result["sort_field_auto_detected"] = True

    if sort_field:
        sweet_spots = detect_sweet_spots(
            configs, criteria, sort_field, sort_direction, threshold, name_field
        )
        traps = detect_traps(configs, criteria, sort_field, tolerance, name_field)
        transitions = compute_tier_transitions(
            configs, criteria, sort_field, sort_direction, name_field
        )
        segment_bests = compute_segment_bests(
            configs, criteria, sort_field, sort_direction, name_field
        )
        result["summary"]["sweet_spots_count"] = len(sweet_spots)
        result["summary"]["traps_count"] = len(traps)
        result["summary"]["segment_count"] = len(segment_bests)
        result["sort_field"] = sort_field
        result["sort_direction"] = sort_direction
        if sort_field_auto:
            result["sort_field_auto_detected"] = True
        result["sweet_spots"] = sweet_spots
        result["traps"] = traps
        result["tier_transitions"] = transitions
        result["segment_bests"] = segment_bests
    else:
        traps = detect_traps(configs, criteria, None, tolerance, name_field)
        if traps:
            result["summary"]["traps_count"] = len(traps)
            result["traps"] = traps
        # Weighted ranking fallback
        ranking = compute_weighted_ranking(configs, criteria, name_field)
        result["weighted_ranking"] = ranking

    return result


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _col_width(values: list[str], header: str) -> int:
    return max(len(header), *(len(v) for v in values)) if values else len(header)


def format_table(
    result: dict[str, Any],
    configs: list[dict[str, Any]],
    criteria: list[dict[str, Any]],
    name_field: str,
) -> str:
    lines: list[str] = []
    s = result["summary"]
    lines.append(
        f"Total: {s['total']}  Pareto: {s['pareto_count']}  "
        f"Ratio: {s['pareto_ratio']:.0%}"
    )
    if "sweet_spots_count" in s:
        lines.append(
            f"Sweet spots: {s['sweet_spots_count']}  Traps: {s.get('traps_count', 0)}"
        )
    lines.append("")

    front = result["pareto_front"]
    if front:
        lines.append("== Pareto Front ==")
        cols = [name_field] + [c["name"] for c in criteria]
        rows = [[str(configs[i].get(c, "")) for c in cols] for i in front]
        widths = [_col_width([r[ci] for r in rows], c) for ci, c in enumerate(cols)]
        lines.append(" | ".join(c.ljust(w) for c, w in zip(cols, widths)))
        lines.append("-+-".join("-" * w for w in widths))
        for row in rows:
            lines.append(" | ".join(v.ljust(w) for v, w in zip(row, widths)))

    if result.get("front_tradeoffs"):
        ft = result["front_tradeoffs"][0]
        lines.append("")
        lines.append("== Front Trade-offs ==")
        for item in ft["items"]:
            parts = []
            if item["strengths"]:
                parts.append(f"strong: {', '.join(item['strengths'])}")
            if item["weaknesses"]:
                parts.append(f"weak: {', '.join(item['weaknesses'])}")
            lines.append(
                f"  {item['name']}: {'; '.join(parts) if parts else 'balanced'}"
            )
        for pw in ft["pairwise"][:5]:
            a_at = ", ".join(pw["a_better_at"]) if pw["a_better_at"] else "-"
            b_at = ", ".join(pw["b_better_at"]) if pw["b_better_at"] else "-"
            lines.append(
                f"  {pw['a']} vs {pw['b']}: {pw['a']}>{a_at} | {pw['b']}>{b_at}"
            )

    if result.get("sweet_spots"):
        lines.append("")
        lines.append("== Sweet Spots ==")
        for ss in result["sweet_spots"][:5]:
            lines.append(
                f"  {ss['name']} (gain: {ss['gain_score']:.2f}) — {ss['reason']}"
            )

    if result.get("segment_bests"):
        lines.append("")
        lines.append("== Best per Segment ==")
        for seg in result["segment_bests"]:
            alt = (
                f" (alt: {', '.join(seg['alternatives'])})"
                if seg["alternatives"]
                else ""
            )
            lines.append(
                f"  [{seg['range']}] {seg['best']} (score: {seg['composite_score']:.2f}){alt}"
            )

    if result.get("weighted_ranking"):
        lines.append("")
        lines.append("== Weighted Ranking ==")
        for wr in result["weighted_ranking"][:10]:
            lines.append(
                f"  #{wr['rank']} {wr['name']} (score: {wr['composite_score']:.2f})"
            )

    if result.get("traps"):
        lines.append("")
        lines.append("== Traps ==")
        for t in result["traps"]:
            lines.append(
                f"  {t['name']} <- {t['dominated_by_name']} is better: {t['reason']}"
            )

    if result.get("dominated"):
        lines.append("")
        lines.append(f"== Dominated ({len(result['dominated'])}) ==")
        for d in result["dominated"][:10]:
            doms = ", ".join(db["name"] for db in d["dominated_by"][:2])
            lines.append(f"  {d['name']} <- dominated by {doms}")

    return "\n".join(lines)


def format_markdown(
    result: dict[str, Any],
    configs: list[dict[str, Any]],
    criteria: list[dict[str, Any]],
    name_field: str,
) -> str:
    lines: list[str] = []
    s = result["summary"]

    lines.append("# Pareto Analysis")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total | {s['total']} |")
    lines.append(f"| Pareto optimal | {s['pareto_count']} |")
    lines.append(f"| Pareto ratio | {s['pareto_ratio']:.0%} |")
    if "sweet_spots_count" in s:
        lines.append(f"| Sweet spots | {s['sweet_spots_count']} |")
        lines.append(f"| Traps | {s.get('traps_count', 0)} |")

    front = result["pareto_front"]
    if front:
        lines.append("")
        lines.append("## Pareto Front")
        lines.append("")
        cols = [name_field] + [c["name"] for c in criteria]
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("| " + " | ".join("---" for _ in cols) + " |")
        for i in front:
            vals = [str(configs[i].get(c, "")) for c in cols]
            lines.append("| " + " | ".join(vals) + " |")

    if result.get("front_tradeoffs"):
        ft = result["front_tradeoffs"][0]
        lines.append("")
        lines.append("## Front Trade-offs")
        lines.append("")
        lines.append("| Item | Strengths | Weaknesses |")
        lines.append("| --- | --- | --- |")
        for item in ft["items"]:
            s = ", ".join(item["strengths"]) if item["strengths"] else "-"
            w = ", ".join(item["weaknesses"]) if item["weaknesses"] else "-"
            lines.append(f"| {item['name']} | {s} | {w} |")
        if ft["pairwise"]:
            lines.append("")
            for pw in ft["pairwise"][:5]:
                a_at = ", ".join(pw["a_better_at"]) if pw["a_better_at"] else "-"
                b_at = ", ".join(pw["b_better_at"]) if pw["b_better_at"] else "-"
                lines.append(
                    f"- **{pw['a']}** vs **{pw['b']}**: "
                    f"{pw['a']} wins on {a_at}; {pw['b']} wins on {b_at}"
                )

    if result.get("sweet_spots"):
        lines.append("")
        lines.append("## Sweet Spots")
        lines.append("")
        for rank, ss in enumerate(result["sweet_spots"][:5], 1):
            lines.append(
                f"**{rank}. {ss['name']}** (gain score: {ss['gain_score']:.2f})"
            )
            lines.append(f"   vs {ss['compared_to_name']}: {ss['reason']}")
            lines.append("")

    if result.get("segment_bests"):
        lines.append("")
        lines.append("## Best per Segment")
        lines.append("")
        lines.append("| Range | Best | Score | Alternatives | Items |")
        lines.append("| --- | --- | --- | --- | --- |")
        for seg in result["segment_bests"]:
            alt = ", ".join(seg["alternatives"]) if seg["alternatives"] else "-"
            lines.append(
                f"| {seg['range']} | {seg['best']} | "
                f"{seg['composite_score']:.2f} | {alt} | {seg['item_count']} |"
            )

    if result.get("weighted_ranking"):
        lines.append("")
        lines.append("## Weighted Ranking")
        lines.append("")
        lines.append("| Rank | Item | Composite Score |")
        lines.append("| --- | --- | --- |")
        for wr in result["weighted_ranking"][:10]:
            lines.append(
                f"| {wr['rank']} | {wr['name']} | {wr['composite_score']:.2f} |"
            )

    if result.get("traps"):
        lines.append("")
        lines.append("## Traps")
        lines.append("")
        for t in result["traps"]:
            lines.append(
                f"- **{t['name']}** -> {t['dominated_by_name']}: {t['reason']}"
            )

    if result.get("tier_transitions"):
        lines.append("")
        lines.append("## Tier Transitions")
        lines.append("")
        lines.append("| From | To | Delta | Gain Score | Key Jumps |")
        lines.append("| --- | --- | --- | --- | --- |")
        for tr in result["tier_transitions"]:
            jumps = ", ".join(tr["key_jumps"]) if tr["key_jumps"] else "-"
            lines.append(
                f"| {tr['from_name']} | {tr['to_name']} | "
                f"{tr['delta']:.4g} | {tr['gain_score']:.2f} | {jumps} |"
            )

    return "\n".join(lines)


def format_csv_output(
    result: dict[str, Any],
    configs: list[dict[str, Any]],
) -> str:
    """CSV of pareto front items."""
    front = result["pareto_front"]
    if not front:
        return ""
    buf = io.StringIO()
    cols = list(configs[front[0]].keys())
    writer = csv.DictWriter(buf, fieldnames=cols)
    writer.writeheader()
    for i in front:
        writer.writerow(configs[i])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Multi-criteria Pareto analysis with marginal gain sweet spot detection",
    )
    parser.add_argument(
        "file", nargs="?", default=None, help="Input (JSON/CSV). Omit or - for stdin"
    )

    crit = parser.add_argument_group("criteria (flat mode)")
    crit.add_argument("-M", "--maximize", default="", help="Fields to maximize")
    crit.add_argument("-m", "--minimize", default="", help="Fields to minimize")
    crit.add_argument("-c", "--criteria", default="", help='"field:max,field:min,..."')

    anl = parser.add_argument_group("analysis")
    anl.add_argument(
        "--sort-by", default=None, help="Sort axis for marginal gain analysis"
    )
    anl.add_argument(
        "--sort-dir",
        choices=["asc", "desc"],
        default="asc",
        help="asc=higher costs more (default), desc=lower costs more",
    )
    anl.add_argument("--weights", default=None, help='"field:weight,..."')
    anl.add_argument(
        "--threshold", type=float, default=0.85, help="Sweet spot threshold (0.85)"
    )
    anl.add_argument(
        "--tolerance", type=float, default=0.05, help="Trap proximity ratio (0.05)"
    )

    out = parser.add_argument_group("output")
    out.add_argument(
        "-f",
        "--format",
        choices=["table", "json", "csv", "markdown"],
        default="json",
        help="Output format (default: json)",
    )
    out.add_argument(
        "--name-field", default="name", help='Name field (default: "name")'
    )

    args = parser.parse_args()

    configs, structured_meta = load_input(args.file)
    if not configs:
        print("Error: no items in input", file=sys.stderr)
        return 1

    maximize = [f.strip() for f in args.maximize.split(",") if f.strip()]
    minimize = [f.strip() for f in args.minimize.split(",") if f.strip()]
    criteria_arg = parse_criteria_arg(args.criteria) if args.criteria else []
    weight_overrides = parse_weights_arg(args.weights) if args.weights else {}

    criteria = build_criteria(
        structured_meta, maximize, minimize, criteria_arg, weight_overrides
    )

    sort_field = args.sort_by
    if not sort_field and structured_meta:
        sort_field = structured_meta.get("cost_field")

    result = analyze(
        configs,
        criteria,
        sort_field=sort_field,
        sort_direction=args.sort_dir,
        threshold=args.threshold,
        tolerance=args.tolerance,
        name_field=args.name_field,
    )

    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.format == "table":
        print(format_table(result, configs, criteria, args.name_field))
    elif args.format == "markdown":
        print(format_markdown(result, configs, criteria, args.name_field))
    elif args.format == "csv":
        print(format_csv_output(result, configs))

    ps = result["summary"]
    if result.get("sort_field_auto_detected"):
        print(
            f"Auto-detected sort-by: {result['sort_field']}",
            file=sys.stderr,
        )
    print(
        f"Pareto: {ps['pareto_count']}/{ps['total']} ({ps['pareto_ratio']:.0%})",
        file=sys.stderr,
    )
    if "sweet_spots_count" in ps:
        parts = [
            f"Sweet spots: {ps['sweet_spots_count']}",
            f"Traps: {ps.get('traps_count', 0)}",
        ]
        if "segment_count" in ps:
            parts.append(f"Segments: {ps['segment_count']}")
        print(", ".join(parts), file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
