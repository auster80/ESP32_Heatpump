# What the data says

Analysis of the Home Assistant InfluxDB (`Homeassistant` bucket), 1 Nov 2025 –
Sep 2026. The reality check the control design (§4) asked for.

**A correction to an earlier draft of this file:** the first pass quoted a
€20–30/winter prize and called the emulator a hobby build. That number came
from analysing last winter's prices, which were an unusually *flat* window. Once
the price trend since March is included, and once it is clear the SG Ready
system is hot-water-only and was off for space heating, the time-shift prize is
2–4× larger and fully uncaptured. The corrected verdict is below.

## Headline: the prize is modest but real

| Quantity | Value |
|---|---|
| Heating electricity, winter | **~1000 kWh** (6.7 kWh/day) |
| Heat delivered | 5 508 kWh |
| **Seasonal COP** | **5.56** — this is a ground-source (brine) machine |
| Mean all-in price | 0.257 €/kWh |
| Winter heating cost | **~€260** |
| Price spread, p10→p90 (last winter) | 0.096 €/kWh — but see below |
| Price spread, p10→p90 (recent months) | **0.17 €/kWh — ~3× wider** |
| Time-shift saving, last winter's prices | €37 / winter |
| **Time-shift saving, recent spreads** | **€90–130 / winter** |

The COP of 5.56 keeps the absolute cost low: a brine heat pump turns €260 of
electricity into a warm house. But the saving is set by the price **spread**,
not the level, and here the first pass was misled by its own window. **Last
winter was an unusually flat-price period** — Nov–Feb intraday spread averaged
0.06 €/kWh. From March onward it roughly tripled to ~0.17 €/kWh, and it has
stayed there through summer 2026 as the mean price rose ~9 %:

| Month | Mean €/kWh | Mean intraday spread |
|---|---|---|
| 2025-11 | 0.261 | 0.072 |
| 2025-12 | 0.254 | 0.054 |
| 2026-02 | 0.242 | 0.057 |
| 2026-04 | 0.238 | 0.172 |
| 2026-08 | 0.287 | 0.185 |
| 2026-09 | 0.336 | 0.168 |

Recompute the prize on the same 1000 kWh of heating, shifting into the cheapest
quarter of each day:

- **at last winter's flat prices: €37 / winter**
- **at recent wide spreads: €98 / winter** (34 % off the heating portion)
- a colder winter at higher prices (1300 kWh): **~€128 / winter**

Whether the coming winter looks flat or wide is the real uncertainty. Wider
spreads are the structural trend (solar build-out, more volatility), and winter
keeps the evening-peak-versus-overnight-trough swing even without midday solar,
so €60–100 is the honest central estimate rather than the €20–30 first quoted.

## Two things that are already fine

**Cycling is not a problem.** 8.1 compressor starts/day, median run 35 min,
only 8 % of runs under 10 min. The buffer is doing its job; `CyclingModel`'s
worry about half-load short-cycling does not bite at this install. There is no
cycling problem to solve.

**Nothing is capturing the prize today.** Compressor starts peak at 02:00 and
fire at an average price percentile of 45 — but that is just where overnight
heat demand falls, not price control. The SG Ready system is **hot-water only
and was not active last winter**, so space heating ran on the pure
weather-compensated curve with no price awareness at all. The whole time-shift
prize is therefore uncaptured and on the table, not an incremental slice.

## The real finding: the house runs warm

| Room temperature | Share of winter |
|---|---|
| below 20 °C | 5 % |
| **above 22 °C** | **44 %** |
| median | 21.9 °C |

The house spends nearly half the winter above 22 °C and almost never gets cold.
That overheating is the largest inefficiency in the data, and it is **free** to
fix: lower the heating curve slope or the comfort setpoint by ~1 K. Each 1 K of
average indoor temperature is roughly 6–8 % of heat demand, so this is worth
roughly €18/winter — free, and it makes the house *more* comfortable, not less.
At last winter's flat prices this rivalled the time-shift prize; at today's
wider spreads the time-shift is the larger of the two. **They are independent
and additive** — do both, and a lower curve also lifts COP by dropping flow
temperature.

## Recommendation

1. **Lower the curve first.** Drop the HK1 comfort setpoint / curve slope ~1 K
   and re-check the room distribution over a few weeks. Biggest single saving,
   free, reversible from the FEK.
2. **Keep the existing SG Ready DHW + heating control.** It works and already
   shifts toward cheap hours.
3. **The emulator now earns its keep.** With the space-heating prize fully
   uncaptured and spreads ~3× last winter's, €60–100/winter against ~€55 of
   parts is roughly a one-winter payback — plus the interest of the build. This
   is a real project again, not only a hobby. The caveat is spread risk: if the
   coming winter reverts to last winter's flatness the payback stretches to two
   or three winters.
4. **If any automated shifting is extended, put it on DHW, not space heat.**
   The tank is a discrete, larger thermal batch with a bigger temperature lift,
   so it shifts more energy per decision — and it is already on SG Ready.

## Caveats

- `b` in `HouseModel` (shift → indoor gain) still cannot be fitted: last winter
  has no shift data. Unchanged by this analysis.
- Savings scale with the spot spread. A winter with volatile prices (a cold
  snap, low wind) would widen p10→p90 and raise the prize; 2025-26 was
  moderate. The €20–30 is typical, not a floor.
- The 44 % > 22 °C includes solar-gain afternoons the heat pump did not cause;
  the curve cut helps the heating-driven part, not the sunny-window part.
