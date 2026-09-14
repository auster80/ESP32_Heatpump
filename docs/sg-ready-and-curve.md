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

**Root cause, from the Node-RED flow** (`existing-home-assistant-control.md`):
the DHW logic has fixed safety overrides at **05:00 and 16:00** and heats within
human "morning" and "evening" windows. Those clock times sit near the daily
price peaks — 05:00 averaged 0.343, 16:00 averaged 0.341, both well above the
0.19 midday trough. The control is time-scheduled dressed as price-aware, and
the chosen times are close to the worst of the day.

**The fix is pure software** and larger than the emulator's prize: point the DHW
window at the day's actual cheapest hours (overnight in winter, midday in
summer), keep only a genuine legionella floor as the fixed override, and let the
well-insulated tank carry heat to the next draw. On 650 kWh/winter of DHW at
COP 3.48, closing even two-thirds of the 37 % gap is ~€45/winter, for an evening
of Node-RED editing and no parts.

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
