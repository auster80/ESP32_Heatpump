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

## Correction: at real shop prices the knee moves to three modules

The table above priced a US5000 at €1 450, the typical 2026 retail figure. An
actual cart (Sep 2026) shows **€706,86 per module** plus €37 bracket and a €15
cable set — roughly half. Rerun at that price:

| Size | Cost (€707 inc VAT) | Saving/yr | Payback | Net at 10 y | Marginal module |
|---|---|---|---|---|---|
| 4.8 kWh | 3 549 € | 327 € | 10.8 y | −277 € | 2.3 y |
| 9.6 kWh | 4 293 € | 523 € | 8.2 y | +939 € | 3.8 y |
| **14.4 kWh** | **5 037 €** | **645 €** | **7.8 y** | **+1 411 €** | **6.1 y** |
| 19.2 kWh | 5 781 € | 706 € | 8.2 y | +1 275 € | 12.2 y |

At €707 the **third module pays back in 6.1 years** and lifts the ten-year net
to its maximum; the fourth still does not. **14.4 kWh (3 × US5000) is the size
at this price.** If the cart price turns out to be ex-VAT (€855 inc), the third
module pays back in 7.3 years and 14.4 kWh remains the best size, just with
thinner margins.

With the 21 % VAT reclaimed on the whole system as well (see below), 14.4 kWh
pays back in **6.5 years** and clears **+2 285 €** at ten years. The battery
moves from "defensible" to "clearly worthwhile".

## BTW: 21 % applies, but it can be reclaimed — with a catch

Batteries do **not** get the 0 % rate that solar panels have had since 2023;
they carry 21 %. A private person cannot buy one VAT-free. What *is* possible is
to **reclaim** the 21 % afterwards, because the Belastingdienst treats someone
who buys and sells electricity through a battery on a dynamic contract as a
VAT entrepreneur. Five cumulative conditions:

1. The battery is used to buy and sell electricity through your supplier.
2. It has an energy-management system (Victron ESS with dynamic pricing counts).
3. You have a **dynamic energy contract** (Tibber qualifies; it can be arranged
   up to a month after the invoice date).
4. Invoice and energy contract are in your name.
5. **You are not in the KOR** (kleineondernemersregeling) at purchase and
   installation.

Condition 5 is the catch for this house. Most solar owners are in the KOR —
many were placed there after the 2023 panel changes — and **inside the KOR no
VAT can be reclaimed**. Leaving it takes effect from the first day of a
calendar quarter with about four weeks' processing, so it must be done *before*
the invoice, not after. Leaving the KOR also means filing VAT returns and owing
VAT on the electricity you sell, which is why the reclaim is usually netted
against that and the whole thing is worth a tax adviser's half hour before the
order goes in.

## Confirmed: the shop price is ex-VAT

€706,86 is the ex-VAT price, so at checkout a consumer pays **€855,30 per
module** (+21 %). That makes the two cases exact rather than hypothetical — and
the ex-VAT figure is precisely what you end up paying *net* if the reclaim
succeeds, since the reclaim applies to the whole system (inverter, GX,
installation), not just the modules.

| 14.4 kWh (3 × US5000) | Cost | Payback | Net at 10 y | 3rd module pays back |
|---|---|---|---|---|
| Pay VAT, no reclaim (€855/module) | 5 481 € | 8.5 y | +967 € | 7.3 y |
| **VAT reclaimed** (effectively €707/module) | **4 530 €** | **7.0 y** | **+1 918 €** | **6.1 y** |

Three modules is the right size either way; the fourth pays back in 12–15
years in both and is not worth it. The reclaim is worth roughly **€950 up front
and ~1.5 years of payback** — so leaving the KOR before the invoice, if you are
in it, is the single most valuable administrative step in the whole purchase.

## KOR: registered September 2020 — you can leave, and cheaply

Registering for the solar-panel VAT refund in September 2020 put you in the
(new) KOR, and nothing since — including the 2023 move of panels to 0 % — took
you out. So you are almost certainly still in it, and inside it the battery
reclaim is not possible. The good news is that every lock-in that used to make
leaving painful has expired or been abolished:

| Rule | What it means for you |
|---|---|
| Minimum 3 years' participation | **Abolished 1 Jan 2025.** You can leave at any time. |
| Exit takes effect at a quarter start, notify ≥ 4 weeks ahead | To leave **1 Jan 2027**, file by **~1 Dec 2026**. Invoice the battery from January. |
| Re-entry ban: rest of that year + the following year | Out of the KOR for **2027 and 2028**; may re-enter 1 Jan 2029. |
| Battery revision period: 5 years | Re-entering within it *can* claw back reclaimed VAT — **but** |
| **De minimis: revision under €500/year is not applied** | Your ~€950 reclaim revises at ~€190/year — **below €500, so no clawback** even if you re-enter in 2029. |
| Panels' 5-year revision (2020 + 4) | **Ended 2024.** Nothing to repay on the panels. |

Net: leaving the KOR costs two years of quarterly VAT returns (mostly small
amounts — VAT owed on electricity sold, netted against nothing much) and gains
about **€950**, with no revision exposure on either the battery or the panels.
Clearly worth it. The timing also fits the recommendation to buy for 2027.

Two things to confirm with the Belastingdienst or an adviser before relying on
this: that the €500 de-minimis applies to your re-entry case as read here, and
whether a private-use correction (privégebruik) is applied to a household
battery in the years you are registered. Both are minor against the €950, but
this is tax, not engineering.

## Buying in Germany: 0 % VAT exists there — whether it reaches you depends on the sale

Germany has applied a **0 % VAT rate (Nullsteuersatz, § 12 Abs. 3 UStG) to
home batteries and PV components since 1 Jan 2023**, for systems on or near
residential buildings. Whether a Dutch buyer benefits depends entirely on how
the goods change hands:

| How | VAT you pay | Why |
|---|---|---|
| **Shipped to the Netherlands** | **21 % Dutch VAT** | B2C distance sale: since July 2021 the seller must charge the *destination* country's VAT (OSS). The German 0 % does not travel. |
| **Collected in person in Germany** | **0 % — plausibly** | The supply is then domestic German; the German rate applies. A private buyer who takes goods home pays VAT where bought and owes no Dutch acquisition VAT. |

The collection route is legal for a private individual, but has one practical
uncertainty: the 0 % rate is conditioned on installation on/near a residential
building, and the BMF guidance does not spell out whether that building may be
abroad. Some German shops apply 0 % to any collector who confirms residential
use; others require a German installation address. **Ask the shop before
driving.**

If it works, it dominates the Dutch route: the same ~€707 net per module, but
with **no KOR exit, no two years of VAT returns, and no revision exposure** —
and the MultiPlus and Cerbo qualify for 0 % as system components if bought
together. Against that: a ~3 h drive for ~120 kg of batteries, and warranty
service across a border.

### The MultiPlus qualifies for the German 0 % too — with the same catch

A MultiPlus-II is a *battery* inverter/charger rather than a PV inverter, but
under § 12 Abs. 3 UStG it counts as an **essential component of a storage
system**, and retrofitting storage to an existing PV installation is expressly
covered. German shops list the MultiPlus-II 48/5000 at 0 % on that basis, so
the whole kit — modules, MultiPlus, Cerbo GX — can in principle be bought at 0 %
together, which is cleaner than buying the batteries at 0 % and the inverter at
21 %.

The catch is the same one as for the batteries, only more visible: several
German shops state the 0 % offer is **"exclusively for private end consumers in
Germany"**. That is shop policy, not the law — the statute conditions the rate
on residential installation, not on a German address — but it means a Dutch
collector has to find a shop willing to apply it. Ask explicitly, for the full
kit, before making the trip. If a shop will do the batteries at 0 % it will
almost always do the MultiPlus on the same declaration.
