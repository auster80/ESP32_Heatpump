# What last winter's data says

Analysis of the Home Assistant InfluxDB (`Homeassistant` bucket), 1 Nov 2025 –
31 Mar 2026. This is the reality check the control design (§4) asked for, and
it changes the recommendation. **Read this before building anything.**

## Headline: the prize is small

| Quantity | Value |
|---|---|
| Heating electricity, winter | **~1000 kWh** (6.7 kWh/day) |
| Heat delivered | 5 508 kWh |
| **Seasonal COP** | **5.56** — this is a ground-source (brine) machine |
| Mean all-in price | 0.257 €/kWh |
| Winter heating cost | **~€260** |
| Price spread, p10→p90 | **0.096 €/kWh** — narrow |
| Realistic time-shift saving | **€20–30 / winter** |

The COP of 5.56 is the root of it: a brine heat pump turns €260 of electricity
into a warm house, so even a large *fraction* saved is a small *number*. And
the Dutch all-in price is mostly tax and network charge — the movable spot
component is a thin slice, so the day's p10→p90 spread is only ~0.10 €/kWh.
Shift every kilowatt-hour of heating into the cheapest quarter of the day and
the bill falls ~12–15 % of the heating portion — €20–30 over a winter.

## Two things that are already fine

**Cycling is not a problem.** 8.1 compressor starts/day, median run 35 min,
only 8 % of runs under 10 min. The buffer is doing its job; `CyclingModel`'s
worry about half-load short-cycling does not bite at this install. There is no
cycling problem to solve.

**Heating already leans cheap.** Compressor starts fire at an average price
percentile of 45 (50 would be random) and peak at 02:00, the cheapest hours.
The existing Node-RED SG Ready control is already capturing part of the €20–30,
so the *incremental* prize from the emulator is smaller still.

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
more than the time-shifting the emulator was for — at zero hardware cost, and it
makes the house *more* comfortable, not less.

## Recommendation

1. **Lower the curve first.** Drop the HK1 comfort setpoint / curve slope ~1 K
   and re-check the room distribution over a few weeks. Biggest single saving,
   free, reversible from the FEK.
2. **Keep the existing SG Ready DHW + heating control.** It works and already
   shifts toward cheap hours.
3. **Treat the outdoor-sensor emulator as a hobby build, not an investment.**
   Its incremental saving over what the SG Ready control already does is a few
   euros a winter against ~€55 of parts and the build effort. Worth doing for
   the interest and the learning; not worth doing to save money.
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
