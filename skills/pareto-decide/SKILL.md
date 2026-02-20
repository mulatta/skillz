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

**pareto_ratio >= 0.5** — Too many items on frontier, sweet spots matter:
- Focus on `sweet_spots` — items with highest `gain_score`
- Explain `tier_transitions` — where the biggest value jumps happen
- gain_score > 1.0 means proportionally more improvement than sort-axis cost
- gain_score > 1.3 is a strong sweet spot

**traps exist** — Always warn:
- Items that look similar but are strictly worse on key metrics
- Recommend the dominating alternative

## `--sort-by` Judgment

Use `--sort-by` when items have a natural "investment axis" — something you spend more of to get other things:

| Axis | Direction | Example |
|------|-----------|---------|
| price | asc | Product lineups, cloud instances |
| weight | asc | Hardware, portability trade-off |
| complexity | asc | Algorithm comparison |
| latency | desc | Lower is better, more investment to reduce |
| learning_curve | asc | Language/framework comparison |

Omit `--sort-by` when no clear investment axis exists (e.g., comparing programming paradigms on abstract criteria).

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
  --sort-dir DIR    asc (default) or desc
  --weights W       "field:weight,..." overrides
  --threshold T     Sweet spot gain_score threshold (default: 0.85)
  --tolerance T     Trap proximity ratio (default: 0.05)

Output:
  -f, --format      json (default), table, markdown, csv
  --name-field      Item name field (default: "name")
```
