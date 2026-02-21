---
name: pareto-decide
description: Multi-criteria Pareto analysis with sweet spot detection. Use when comparing items/configs/products across multiple criteria to find optimal choices. Triggers on 'sweet spot', 'best value', 'pareto', 'compare options', '가성비', '최적', 'which config', 'trade-off'.
argument-hint: [items or description]
---

# Pareto Analysis

Find optimal items from multi-criteria comparisons. Handles both simple Pareto and product-lineup sweet spot detection in a single call.

## When to Use

- Comparing options with multiple criteria (cost vs perf vs size, etc.)
- Product lineup analysis (Apple, GPU, cloud instances, VPS)
- Any multi-criteria optimization

## Workflow (single call, no re-runs)

### 1. Collect Items

From user input or web_search. Build JSON:

**Flat format** (simple comparisons):
```json
[
  {"name": "Option A", "cost": 10, "perf": 90, "ram": 32},
  {"name": "Option B", "cost": 5, "perf": 80, "ram": 16}
]
```

**Structured format** (product lineups with weights):
```json
{
  "product_line": "Mac Desktop 2025",
  "cost_field": "price_usd",
  "criteria": [
    {"name": "ram_gb", "direction": "maximize", "weight": 0.30},
    {"name": "mem_bw_gbps", "direction": "maximize", "weight": 0.35},
    {"name": "gpu_cores", "direction": "maximize", "weight": 0.25},
    {"name": "ssd_tb", "direction": "maximize", "weight": 0.10}
  ],
  "configs": [
    {"name": "Mac Mini M4 16GB", "price_usd": 599, "ram_gb": 16, "mem_bw_gbps": 120, "gpu_cores": 10, "ssd_tb": 0.256}
  ]
}
```

Note: `cost_field` auto-maps to `--sort-by`.

### 2. Run Analysis

```bash
# Flat input
echo '$JSON' | pareto-decide -m cost -M perf,ram --sort-by cost

# Structured input (cost_field auto-detected)
pareto-decide /tmp/specs.json

# Override weights
pareto-decide /tmp/specs.json --weights "ram_gb:0.3,mem_bw_gbps:0.35"
```

### 3. Interpret Results (no re-run needed)

Output JSON always includes `summary.pareto_ratio`. Use this to decide emphasis:

**pareto_ratio < 0.5** — Pareto alone discriminates well:
- Focus on `pareto_front_names` — these are the clear winners
- Explain why each dominated item is worse (use `dominated[].dominated_by[].advantages`)

**pareto_ratio >= 0.5** — Too many items on frontier, use deeper analysis:
- `front_tradeoffs` — each front item's strengths/weaknesses + pairwise comparison
- `sweet_spots` — items with highest `gain_score`
- `segment_bests` — "best in this price range" recommendations
- `tier_transitions` — where the biggest value jumps happen
- gain_score > 1.0 means proportionally more improvement than sort-axis cost
- gain_score > 1.3 is a strong sweet spot

**segment_bests** — Use for "which is best at this budget?" questions:
- Each segment shows the best item in that sort-axis range
- Present as "In the $X-$Y range, Z is optimal because..."
- `alternatives` lists other front items in the same range

**weighted_ranking** — Available when no sort axis (no `--sort-by`, no auto-detect):
- Composite score ranking across all items
- Use when no natural investment axis exists

**traps exist** — Always warn:
- Items that look similar but are strictly worse on key metrics
- Recommend the dominating alternative

## `--sort-by` and Auto-detection

**Auto-detection**: When `--sort-by` is omitted and exactly one `-m` (minimize) criterion exists, it is automatically used as the sort axis. stderr shows `"Auto-detected sort-by: <field>"`. This enables sweet spots, segment bests, and tier transitions without explicit `--sort-by`.

Use `--sort-by` explicitly when items have a natural "investment axis" — something you spend more of to get other things:

| Axis | Direction | Example |
|------|-----------|---------|
| price | asc | Product lineups, cloud instances |
| weight | asc | Hardware, portability trade-off |
| complexity | asc | Algorithm comparison |
| latency | desc | Lower is better, more investment to reduce |
| learning_curve | asc | Language/framework comparison |

Omit `--sort-by` when no clear investment axis exists (e.g., comparing programming paradigms on abstract criteria). In that case, `weighted_ranking` provides a composite-score-based ranking.

## Weight Guidelines

Adjust based on user's stated priorities:

| Use case | Suggested weights |
|----------|------------------|
| LLM inference | mem_bw:0.35, ram:0.30, gpu:0.25, ssd:0.10 |
| Video editing | gpu:0.35, ram:0.25, ssd:0.20, cpu:0.20 |
| General compute | cpu:0.30, ram:0.25, gpu:0.25, ssd:0.20 |
| Cloud hosting | cost:0.35, cpu:0.25, ram:0.25, network:0.15 |

## CLI Reference

```
pareto-decide [FILE] [OPTIONS]

Criteria (flat mode):
  -M, --maximize    Fields to maximize (comma-sep)
  -m, --minimize    Fields to minimize (comma-sep)
  -c, --criteria    "field:max,field:min,..."

Analysis:
  --sort-by FIELD   Investment axis (enables sweet spots/traps/transitions)
                    Auto-detected when exactly one -m criterion exists
  --sort-dir DIR    asc (default) or desc
  --weights W       "field:weight,..." overrides
  --threshold T     Sweet spot gain_score threshold (default: 0.85)
  --tolerance T     Trap proximity ratio (default: 0.05)

Output:
  -f, --format      json (default), table, markdown, csv
  --name-field      Item name field (default: "name")
```

## Output Keys

| Key | When | Description |
|-----|------|-------------|
| `pareto_front` | always | Indices of non-dominated items |
| `dominated` | always | Dominated items with dominators |
| `front_tradeoffs` | front >= 2 | Per-item strengths/weaknesses + pairwise trade-offs |
| `sweet_spots` | sort axis present | High gain_score items along sort axis |
| `segment_bests` | sort axis present | Best item per equal-width range of sort axis |
| `tier_transitions` | sort axis present | Sequential jumps along sort axis |
| `traps` | always checked | Items close on sort axis but strictly worse |
| `weighted_ranking` | no sort axis | All items ranked by composite score |
| `sort_field_auto_detected` | auto-detect | `true` when sort field was auto-detected |
