# Two things the live system got wrong

Read from the running plant on 2026-09-14: the heat pump's current curve
settings over Modbus, and the SG Ready DHW control's effectiveness from the
InfluxDB history. Both point at changes that cost nothing and beat the emulator.

## 1. Current heating curve (live Modbus read)

| Register | Parameter | Value |
|---|---|---|
| 1501 | HK1 comfort room setpoint | **21.5 °C** |
| 1502 | HK1 ECO room setpoint | 20.5 °C |
| 1503 | HK1 heating-curve slope | **0.20** |
| 1509 | DHW comfort | 55 °C |
| 1510 | DHW ECO | 40 °C |
| 1500 | operating mode | 5 (summer / DHW-only, as expected in September) |

The house sat at a median 21.9 °C last winter and above 22 °C for 44 % of it,
against a **21.5 °C setpoint** — so it ran about 0.4 K warmer than commissioned,
most of it solar gain the curve cannot see.

**The curve cut, concretely:** drop register 1501 from 215 to **205** (21.5 →
20.5 °C). The manual states a room-setpoint change is a *parallel shift* of the
whole curve, so this lowers flow temperature at every outdoor temperature by the
equivalent of 1 K of room target. Slope 0.20 is already shallow and appropriate
for floor heating; leave it. Expect ~6–8 % less heat (~€15–20/winter) and a
small COP gain from the lower flow temperature. Reversible in one write from the
FEK. Watch the room a couple of weeks; if any room gets cool, nudge back to 210.

## 2. SG Ready DHW control: not working

Evaluated over 1 Aug – 14 Sep 2026, when SG Ready is active and DHW is the only
load (no space heating in summer, so every compressor start is a DHW start).

| Metric | Value | Verdict |
|---|---|---|
| Compressor start, avg price percentile | **52** | worse than random (50) |
| DHW starts in the cheap third of days | 37 % | should be ~100 % |
| DHW starts in the expensive third | 41 % | |
| Mean price paid for DHW | 0.302 €/kWh | flat-day average 0.299 |
| **Saving vs no control at all** | **−1 %** | **none** |
| Cost left on the table vs cheapest 4 h | **37 %** | ~€60–70/winter |

DHW heating clusters at **00–01, 18–20, and midday**. The 18–20 evening block is
the daily price *peak* (~0.39 €/kWh); the cheapest hours (09–13, ~0.19, midday
solar) are barely used. Water temperature is fine — median 53 °C — so comfort is
not the constraint; the timing is simply price-blind.

### Live DHW configuration (Modbus, 2026-09-14)

| Register | Parameter | Value |
|---|---|---|
| 1509 | DHW **Komfort** setpoint | **55.0 °C** |
| 1510 | DHW **ECO** setpoint | **40.0 °C** |
| 4000 | SG Ready enabled | **1 (on)** |
| 5000 | SG Ready operating state | 2 (Normal) |
| 522 | **active** DHW setpoint right now | **40.0 °C** (ECO) |
| 521 | tank actual | 54.4 °C |

The active setpoint tracks the SG Ready state, and the logged history over
Aug–Sep shows all four levels in use:

| Active setpoint | Meaning | Share of time |
|---|---|---|
| 10.0 °C | SG Ready **Blocked** (1) | 10.2 % |
| **40.0 °C** | **ECO — the resting floor** | **71.4 %** |
| 55.0 °C | Comfort (3) — commanded heat | 17.7 % |
| 60.0 °C | Ordered (4) | 0.7 % |

### Why — and a correction

The 05:00 and 16:00 checks are a *safety net*, and the data clears them:

| Check | Mean tank temperature | Days below the 46 °C threshold |
|---|---|---|
| 05:00 | 55.0 °C | **0 of 17** |
| 16:00 | 53.8 °C | **0 of 15** |

**The safety override never fires.** Neither it nor its 46 °C threshold costs
anything.

Measured tank behaviour: **standing loss is 0.15 K/h**, so from 55 °C the tank
needs **~61 hours** to fall to 46 °C. It is emptied by draws, not by time.

**Correction to an earlier draft of this file.** It claimed the controller
"boosts but never blocks", letting the WPM free-run its own hysteresis. The
register history shows that is wrong on both counts: the system *does* block
(10.2 % of the time at the 10 °C setpoint), and the **ECO floor of 40 °C is
itself an effective block** — with the tank at 54 °C and the active setpoint at
40 °C, the pump has no reason to run at all. The WPM is passive most of the
time, exactly as intended.

The real fault is narrower and clearer: **the Comfort raises — which are the
actual heat commands — are timed badly.**

| Setpoint raises (ECO→Comfort), Aug–Sep | 55 events |
|---|---|
| Average price percentile at the raise | **58** (biased expensive) |
| In the cheap third | 15 |
| In the middle third | 14 |
| **In the expensive third** | **26 (47 %)** |

Hour-of-day of those raises clusters at 00–01 (13), 10–11 (13) and **18–21
(17)** — the last being the daily price peak at ~0.39 €/kWh. Nearly half the
heat commands land in the most expensive third of the day.

The cause is the hard-coded search bands: the morning window searches
18:00→06:30 and the evening window 12:00→18:00. In August the cheapest hours are
**09:00–13:00** (0.184–0.217 €/kWh, midday solar) while the overnight band the
"morning" window is confined to costs **0.31**. The controller cannot reach the
cheap hours because they lie outside both bands — and the evening raises at
18–21 fall outside *both* windows entirely, so they are draw-triggered top-ups
issued at whatever moment the logic noticed, with no price test at all.

### What actually triggers the expensive heating

Classifying every setpoint raise by the tank temperature in the 20 minutes
before it — low means a draw emptied it, warm means the tank did not need it:

| Expensive-third raises (19) | Count | |
|---|---|---|
| **DEMAND — tank at/below 43 °C** | **9 (47 %)** | evening draws, exactly as theorised |
| **OPPORTUNISTIC — tank still 50–55 °C** | **7 (37 %)** | pure waste |
| marginal (43–50 °C) | 3 (16 %) | |

Mean tank minimum before an expensive raise is 44.5 °C, against 49.5 °C before a
cheap one — the expensive ones really are being forced by depletion.

**The evening-shower theory is right**, and the draws are large:

| Evening draws (17:00–22:00), 11 events | |
|---|---|
| Mean start → end | **49.8 °C → 38.7 °C** |
| Mean drop | **11.1 K** |
| p90 drop | 15.8 K |
| Worst observed | **18.6 K** |

The critical number is the *start*: the tank enters the evening at **49.8 °C on
average, not 55 °C**. It has already drifted down during the day and was never
topped up in the cheap afternoon, so the evening draw lands on a half-full tank
and punches straight through the 40 °C floor — forcing a top-up at the 0.39
€/kWh peak.

### Could it be avoided? Yes — entirely

Replaying all 11 evening draws against different starting temperatures. This is
measured in kelvin, so it does not depend on any assumption about tank volume:

| Fill the tank to… | Evening draws that still hit the 40 °C floor |
|---|---|
| 55 °C | 3 of 11 (27 %) |
| 58 °C | 1 of 11 (9 %) |
| **60 °C** | **0 of 11 (0 %)** |

Covering the worst observed draw (18.6 K) needs a start of **58.6 °C**. So
**filling to 60 °C in the cheap window before the evening eliminates every
demand-driven peak-hour trigger observed.**

Two caveats. 60 °C is the top of register 1509's range, leaving only 1.4 K of
margin over the worst draw seen — a longer-than-usual shower run would still
breach it, and there is no headroom left above. And the *opportunistic* 37 % are
not fixed by this at all; they need the price test, since the tank was already
warm when those raises fired.

### The fix — pure software, four changes

1. **Drop the fixed search bands.** Search the whole horizon from now to the
   next draw deadline for the cheapest 2.5 h, rather than confining morning to
   18:00–06:30 and evening to 12:00–18:00. This alone reaches the midday trough
   in summer and keeps the overnight trough in winter, with no seasonal
   switching.
2. **Price-test every raise.** 47 % of heat commands currently fire in the
   expensive third. No raise should be issued above, say, the 40th percentile
   unless the tank is genuinely near the floor. This is the single biggest
   lever — blocking is already partly in place (10 % of the time), so the win is
   in *not commanding heat at the wrong moment*, rather than in adding blocks.
3. **Make reheat deadline-aware.** After a draw, do not reheat immediately
   unless the tank is below the floor. Wait for the cheapest hour before the
   next expected draw.
4. **Raise the Comfort fill target, keep the ECO floor low.** This is the
   setpoint optimisation. The ECO floor of 40 °C is doing its job and should
   stay low — it is what keeps the pump passive. But filling only to **55 °C**
   wastes the tank's capacity. Going to **60 °C** (register 1509: 550 → 600)
   widens the usable band from 15 K to 20 K, **a third more energy stored per
   cheap cycle**, and at 0.15 K/h that buys roughly 33 extra hours of coast.
   Fewer fills are then needed, and every one of them can be placed in a cheap
   hour. Check the mixing valve is set correctly first — 60 °C at the tap
   scalds — and note COP falls slightly at the higher lift, which the wider
   price spread more than pays for.

On 650 kWh/winter at ~0.30 €/kWh, DHW costs about **€195/winter**. Moving the
mean paid price from 0.302 toward ~0.22 — conservative against the 0.191
cheapest-4 h ideal — is roughly a **27 % cut, ~€50/winter**, for an evening of
Node-RED editing and no parts. That is comparable to the entire emulator project
and costs nothing.

## Revised priority order

1. **Curve cut** — register 1501 215→205. Free, ~€15–20/winter, +COP.
2. **Fix the DHW schedule** — software only, ~€45/winter, and it makes the
   already-installed SG Ready hardware do what it was for.
3. **The space-heating emulator** — €60–100/winter, ~€55 parts, one-winter
   payback; independent of and additive to the above.

The order is deliberate: the two free/cheap software changes together are worth
about as much as the hardware project, and de-risk the case for it — if they
capture most of the household's price-shifting prize, the emulator is pure
upside rather than the whole bet.
