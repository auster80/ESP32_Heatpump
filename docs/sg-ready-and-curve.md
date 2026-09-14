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

### Why — three causes, none of them the safety windows

The 05:00 and 16:00 checks are a *safety net* (guarantee hot water for the
morning and evening draw), and the data clears them completely:

| Check | Mean tank temperature | Days below the 46 °C threshold |
|---|---|---|
| 05:00 | 55.0 °C | **0 of 17** |
| 16:00 | 53.8 °C | **0 of 15** |

**The safety override never fires.** It is not the problem, and the 46 °C
threshold is not what is costing money.

The measured tank tells the real story:

- **Standing loss is 0.15 K/h.** From 55 °C the tank needs **~61 hours** to fall
  to 46 °C. Heat costs essentially nothing to store, so the tank is a far better
  battery than the control treats it as.
- The tank is only emptied by **draws**, not by time. Daily minimum averages
  ~36 °C — showers — and the system then reheats *immediately*.

So the three actual causes:

1. **The search bands are hard-coded to a winter price shape.** The morning
   window searches 18:00→06:30 and the evening window 12:00→18:00. In August the
   cheapest hours are **09:00–13:00** (0.184–0.217 €/kWh, midday solar) and the
   overnight band the "morning" window is confined to costs **0.31**. The
   controller cannot reach the cheap hours because they lie outside both bands.
2. **It boosts but never blocks.** `Comfort` was asserted 40 % of the time while
   the blocking contact was on only 21 %. Outside a window the logic sets
   `targetState = null` — "no DHW action needed" — and leaves the relays where
   they were. With SG Ready at Normal or Comfort, the WPM runs its *own* DHW
   hysteresis and reheats the moment a draw drops the tank, whatever the price.
   That is why heating lands at 19:02 in the 0.39 €/kWh evening peak.
3. **Reheat is immediate, not deadline-aware.** With 61 hours of standing loss
   there is no reason to refill at 19:00 for a draw at 07:00 the next morning.

**Original root-cause note, from the Node-RED flow** (`existing-home-assistant-control.md`):
the DHW logic has fixed safety overrides at **05:00 and 16:00** and heats within
human "morning" and "evening" windows. Those clock times sit near the daily
price peaks — 05:00 averaged 0.343, 16:00 averaged 0.341, both well above the
0.19 midday trough. The control is time-scheduled dressed as price-aware, and
the chosen times are close to the worst of the day.

### The fix — pure software, four changes

1. **Drop the fixed search bands.** Search the whole horizon from now to the
   next draw deadline for the cheapest 2.5 h, rather than confining morning to
   18:00–06:30 and evening to 12:00–18:00. This alone reaches the midday trough
   in summer and keeps the overnight trough in winter, with no seasonal
   switching.
2. **Block during the expensive tercile.** This is the biggest lever and it is
   currently missing entirely. Assert SG Ready state 1 whenever price is in the
   top third *and* the tank is above a floor. At 0.15 K/h a six-hour block costs
   **under 1 K** of tank temperature, so it is nearly free.
3. **Make reheat deadline-aware.** After a draw, do not reheat immediately
   unless the tank is below the floor. Wait for the cheapest hour before the
   next expected draw.
4. **Set the floor from draws, not from standing loss.** The 46 °C check never
   fires and could be lowered, but that is not where the win is — the binding
   constraint is having enough hot water at 07:00 and 18:00, not the tank
   cooling. Keep a genuine legionella cycle, and set the floor by how much
   drawable water a shower needs.

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
