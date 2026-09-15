# Home battery sizing

Single-phase Victron MultiPlus-II 48/5000 with Pylontech US5000 modules (48 V
LiFePO₄, 4.8 kWh each), sized against **measured** consumption and solar from
the Home Assistant InfluxDB, priced with **real** Tibber hourly prices, and
projected onto next winter. Summer 2026 is excluded — the house was empty — so
**summer 2025** is the representative summer.

## The measured house

From the smart-meter and inverter counters, not estimates:

| | Summer 2025 (Jun–Aug) | Winter 2025-26 (Nov–Mar) |
|---|---|---|
| House load | 26.3 kWh/day | **45.2 kWh/day** |
| PV produced | 38.4 kWh/day | 15.3 kWh/day |
| Grid import | 14.9 kWh/day | 38.9 kWh/day |
| Grid export | **27.0 kWh/day** | 9.0 kWh/day |
| PV self-consumed | 30 % | 41 % |
| Self-sufficiency | 43 % | 14 % |

Two facts drive the sizing. In summer the house exports 27 kWh/day of surplus
solar while importing 15 kWh at night — the classic shift a battery captures.
In winter the load is 45 kWh/day with a ~2 kW overnight baseload (heat pump plus
the rest), and PV covers only 14 %: a battery can only arbitrage price there,
not store your own sun.

Annual import 7 250 kWh exceeds export 3 844 kWh, so under the current rules
every exported kWh is netted 1:1.

## What changes the answer completely: 1 January 2027

The Dutch salderingsregeling (net metering) **ends abruptly on 1 Jan 2027** —
law passed December 2024. Today, exported solar earns the full import price by
netting, so the grid is a free battery and a home battery is worth almost
nothing:

| Annual saving, price-aware control | 4.8 kWh | 9.6 kWh | 14.4 kWh | 19.2 kWh |
|---|---|---|---|---|
| **With net metering (2026)** | 266 € | 444 € | 555 € | 615 € |
| **Without (2027 onward)** | 402 € | 642 € | 793 € | 869 € |

From 2027, exported solar is worth only the bare supply tariff (legal floor
≥ 50 % of it through 2029), while imports still cost the full all-in price. That
gap is what a battery earns. Since any battery bought now is paid back almost
entirely after 2027, the **no-net-metering case is the one to size against**.

## Simulation

Hourly dispatch over the four measured seasons (summer, winter, two shoulders =
365 days), two control strategies, and the export regime above.

- **SELF** — plain self-consumption: charge from PV surplus, discharge to cover
  load. What a basic installation does. Treated as the floor.
- **PRICE** — Victron ESS with dynamic pricing: a per-day dynamic programme with
  perfect foresight that also charges from the grid in cheap hours. An upper
  bound on any real controller, so an **80 % realism haircut** is applied.

Battery model: 4.8 kWh usable per module, 3.5 kW charge/discharge (MultiPlus-II
48/5000: 4 kVA inverter, 70 A charger), 88 % round-trip efficiency.

Prices: measured hourly Tibber prices for each season; **next winter = last
winter's hourly shape with the mean raised 9 %**, the observed 2026 trend.
Export = all-in price minus ~0.165 €/kWh of tax and VAT, i.e. roughly spot.
Using the legal 50 % floor instead changes the result by under 5 %.

## Result: the marginal module is what matters

Annual saving (2027 rules, PRICE × 0.8), and what each extra module adds:

| Size | Modules | Installed cost | Saving/yr | Payback | Marginal module | Pays back in |
|---|---|---|---|---|---|---|
| 4.8 kWh | 1 | 4 240 € | 327 € | 13.0 y | +327 €/yr | 4.4 y |
| **9.6 kWh** | **2** | **5 690 €** | **523 €** | **10.9 y** | +196 €/yr | 7.4 y |
| 14.4 kWh | 3 | 7 140 € | 645 € | 11.1 y | +122 €/yr | 11.9 y |
| 19.2 kWh | 4 | 8 590 € | 706 € | 12.2 y | +61 €/yr | 23.8 y |

Cost = MultiPlus-II 48/5000 (~1 290 €) + Cerbo GX (300 €) + installation and
DC protection (~1 200 €) + 1 450 € per module, all incl. VAT.

The value of each added module falls fast: 327 → 196 → 122 → 61 €/yr. The
**second** module pays for itself in 7.4 years, inside the battery's life. The
third needs 11.9 — about the battery's whole economic life. The fourth never
does. **9.6 kWh is the knee.**

Cycle life supports it: the PRICE strategy cycles a 9.6 kWh pack ~480 times a
year, so Pylontech's 6 000-cycle rating lasts ~12 years. A single 4.8 kWh module
works harder (614 cycles/yr, ~10 years) — another reason not to go smaller.

## The honest economics

At the base case **no size pays back inside ten years**: 9.6 kWh is −458 € net
at year ten. The case turns positive on either of two things:

| 9.6 kWh | Saving/yr | Payback |
|---|---|---|
| Base (winter +9 %, spot export) | 523 € | 10.9 y |
| **VAT reclaimed** (allowed when the battery trades on a dynamic contract) | 523 € | **9.0 y** |
| **Winter spread doubles** (partial convergence to the 2026 Mar–Sep pattern) | 612 € | 9.3 y |
| Both | 612 € | 7.7 y |
| Floor: no smart control at all | 445 € | 12.8 y |

Both are plausible rather than speculative — the VAT reclaim is a current rule,
and every month since March 2026 has shown the wider spread — but neither is
certain. A fair summary: **a 9.6 kWh battery is roughly break-even over its
life at today's winter prices, and clearly positive if winter spreads follow
the rest of 2026.** It is not a strong investment; it is a defensible one that
the end of net metering makes progressively better.

## Single phase on a three-phase house

Your meter is three-phase, but the loads are balanced — 37 / 26 / 37 % across
the phases, with the heaviest phase at **2.2 kW** at the 95th percentile of
winter evenings. A 3.5 kW single-phase MultiPlus covers that, and Dutch DSMR
meters net across phases for billing, so discharging into one phase offsets
imports on all three. A single-phase system is sufficient; no need for
three units.

## Assumptions, stated

1. Summer 2025 represents summer; winter 2025-26 represents winter; the two
   measured shoulder seasons fill the year to 365 days.
2. Next-winter prices = last winter's hourly shape, mean +9 %.
3. Net metering ends 1 Jan 2027; the payback horizon is priced without it.
4. Export worth ≈ spot (all-in − 0.165 €/kWh); the legal ≥50 % floor is a
   sub-5 % sensitivity.
5. 4.8 kWh usable per US5000. Its nominal is 4.8 kWh and 90 % DoD is usual, so
   this is ~10 % optimistic; savings scale accordingly.
6. 3.5 kW power cap, 88 % round-trip efficiency.
7. Perfect-foresight dispatch × 0.8 realism; a plain self-consumption install
   sits at the SELF floor.
8. Hardware at 2026 Dutch retail; installation ~1 200 €.
9. No EV modelled separately — the car charger is already inside the measured
   grid data. If charging moves to the battery's cheap-hour window it competes
   for the same 3.5 kW; if it happens at 11 kW it swamps the battery entirely.

## Recommendation

**MultiPlus-II 48/5000 + 2 × Pylontech US5000 (9.6 kWh) + Cerbo GX, single
phase, run as Victron ESS with dynamic pricing.** Buy it for 2027, not for
2026. Do not buy a third module at today's prices; the ESS is modular, so add
one later only if winter spreads widen the way spring 2026 did.
