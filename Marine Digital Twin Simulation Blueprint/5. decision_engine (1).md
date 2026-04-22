# Phase 05 — Decision Engine
**Deliverable:** `decision_engine.md`
**Author:** Dhiraj Chavan | Quantum Track |

---

## Why this phase matters more than the simulation itself

All the work in Phases 1–4 produces numbers — corrosion depths, coating thicknesses, barnacle densities, risk scores. But a ship engineer or fleet manager does not want to look at tables of numbers. They want to know: **what do I need to do, and when?**

The decision engine converts simulation outputs into concrete, actionable instructions. Without this layer, the twin is just a data store nobody knows what to do with. With it, the system becomes an intelligent maintenance advisor.

---

## Four Main Decision Outputs

```
1. MAINTENANCE SCHEDULE        2. REPAINTING TIMELINE
   Project corrosion forward      Sort zones by coating thickness
   Find date threshold crossed    URGENT  = below 15 µm threshold
   Add 14-day safety buffer       WARNING = 15–25 µm, watch zone
   Output: zone + action + date   Output: priority queue + dates

3. FUEL LOSS IN DOLLARS        4. RISK ZONE MAP
   barnacle density × drag        0.4 × corrosion + 0.3 × coating
   drag × area = fuel penalty %   0.2 × fouling + 0.1 × flow stress
   × fuel cost = annual $         Score 0.0–1.0 per zone per week
   Output: live cost on dashboard Output: colour map + alerts
```

---

## Decision Output 1 — Maintenance Schedule

The engine projects each zone's corrosion depth forward in time, calculates when it will cross the warning and critical thresholds, subtracts a 14-day safety buffer, and outputs a scheduled maintenance date.

```python
for zone in ship.all_zones:
    # How long until this zone hits the warning threshold?
    days_to_warning = (WARNING_THRESHOLD - zone.corrosion_depth) \
                      / zone.corrosion_rate * 365

    # Schedule maintenance before that, with safety buffer
    maintenance_due_date = today + days_to_warning - 14

    # What action does this zone need?
    action = 'spot-coat'      if zone.risk_score < 0.6 else \
             'full-repaint'   if zone.risk_score < 0.8 else \
             'drydock-inspect'

# Example output:
# Zone Z_022 (Keel-Midship):
# Current depth: 1.1mm | Rate: 0.3mm/year | Failure projected: 2025-03-14
# Maintenance due: 2025-02-28 | Action: spot-coat + inspection
```

---

## Decision Output 2 — Repainting Timeline (Priority Queue)

Zones are sorted from thinnest to thickest coating. Output is a priority queue — thinnest zones are URGENT, zones approaching the threshold are WARNING, zones with plenty of coating are OK.

```
Repainting Priority Queue (sorted by coating thickness, thinnest first):

  [URGENT]  Zone Z_012 | coating:   8 µm | repaint in  3 weeks
  [URGENT]  Zone Z_009 | coating:  11 µm | repaint in  5 weeks
  [WARNING] Zone Z_034 | coating:  18 µm | repaint within 2 months
  [WARNING] Zone Z_047 | coating:  22 µm | repaint within 3 months
  [OK]      Zone Z_056 | coating:  87 µm | fine for ~14 months
  [OK]      Zone Z_003 | coating: 141 µm | fine for ~25 months
```

---

## Decision Output 3 — Fuel Loss Due to Barnacles (in dollars)

Takes the biofouling state of every zone, calculates total drag penalty, and converts it to an annual fuel cost in dollars — turning the abstract concept of "barnacles on the hull" into a concrete number on a finance report.

```python
# Step 1: Compute drag contribution from each zone
for zone in ship.all_zones:
    zone.drag_contribution = zone.drag_coefficient * zone.area

# Step 2: Ship-level drag increase vs a perfectly clean hull
total_drag             = sum(zone.drag_contribution for zone in ship.all_zones)
reference_drag         = sum(zone.base_drag * zone.area for zone in ship.all_zones)
drag_increase_fraction = (total_drag - reference_drag) / reference_drag

# Step 3: Convert to fuel penalty
fuel_penalty_percent = drag_increase_fraction * PROPULSIVE_EFFICIENCY * 100

# Step 4: Convert to annual cost
extra_fuel_tonnes = fuel_penalty_percent / 100 * annual_fuel_consumption_tonnes
annual_cost       = extra_fuel_tonnes * BUNKER_FUEL_PRICE_USD_PER_TONNE

# Example output at current fouling level:
# Drag increase: +4.3% | Fuel penalty: +3.1% | Annual extra cost: ~$82,000
# Cost of one hull cleaning: ~$15,000 → net saving from cleaning: $67,000/year
```

---

## Decision Output 4 — Risk Zone Map (colour-coded)

Every zone gets a risk score from 0.0 to 1.0 every timestep. Corrosion gets the highest weight (0.4) because structural failure is the most dangerous and expensive consequence.

```python
risk_score = (  0.40 * normalise(corrosion_depth,   max=CRITICAL_CORROSION)
              + 0.30 * normalise(1 - coating_thick,  max=MAX_COATING)
              + 0.20 * normalise(barnacle_density,   max=HEAVY_FOULING)
              + 0.10 * normalise(flow_velocity,      max=MAX_FLOW) )

# Weight reasoning:
# 40% corrosion   — structural damage, most dangerous and expensive
# 30% coating     — controls everything else, early warning signal
# 20% fouling     — operational cost driver (fuel)
# 10% flow stress — coating wear driver, secondary indicator
```

**Risk scale:**
`0.0–0.3 → LOW (green)` · `0.3–0.6 → MEDIUM (yellow)` · `0.6–0.8 → HIGH (orange)` · `0.8–1.0 → CRITICAL (red)`

---

## Thresholds — the hard limits that trigger actions

| Variable | Warning Threshold | Critical Threshold | What Happens When Crossed |
|----------|------------------|--------------------|--------------------------|
| `corrosion_depth` | 1.5 mm | 3.0 mm | Spot repair required / structural inspection |
| `coating_thickness` | 20 µm | 10 µm | Repaint zone / emergency recoat |
| `barnacle_density` | 50 /m² | 150 /m² | Schedule hull cleaning / emergency clean |
| `fuel_penalty` | 3% | 8% | Schedule cleaning / emergency port stop |
| `risk_score` | 0.60 | 0.80 | Escalating alert / immediate intervention |

---

## Alert Types

**Zone Alert** — One zone's variable crosses a threshold → Dashboard notification sent to fleet engineer
```
[ZONE ALERT] Zone Z_031 | corrosion_depth = 1.7mm (WARNING: 1.5mm)
Recommended action: schedule inspection within 14 days
```

**Ship-Level Alert** — An aggregate ship metric crosses a threshold → Email + SMS to fleet manager
```
[SHIP ALERT] Fuel penalty reached 5.2% — above WARNING threshold
Cause: heavy fouling in keel zones Z_040 to Z_048
```

**Predictive Alert** — Simulation forecasts a threshold crossing within 30, 60, or 90 days → Weekly digest email to fleet planner
```
[PREDICTIVE] Zone Z_022 will reach CRITICAL corrosion in 47 days
Confidence: 87% | Recommended: pre-book drydock slot
```

---

## Optimisation Outputs

```python
# 1. Optimal cleaning interval (balances cleaning cost vs accumulated fuel penalty)
optimal_interval_months = minimise(cleaning_cost + total_fuel_penalty_over_period)
# Example: clean every 14 months → saves net $52,000/year after cleaning cost

# 2. Route-based fouling forecast
# Route A (tropical waters): fouling rate 2.1× faster → add cleaning stop in 8 months
# Route B (North Atlantic):  fouling rate standard    → no change to schedule
```
