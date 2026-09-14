# Recommendations

Final position after reading the plant live and the full InfluxDB record. The
ranking changed once the prize was computed **per month**, because price spread
and load are seasonal in opposite directions.

## The fact that reorders everything

Achievable saving on shifted load (cheapest 25 % of day vs day mean), measured:

| Season | Spread available |
|---|---|
| **Nov–Feb** | **11 %** |
| **Mar–Sep** | **34 %** |

Spreads are three times wider outside the heating season. But **space heating
only runs Nov–Mar**, so it is structurally confined to the months where
time-shifting pays least. Hot water runs all year and is therefore exposed to
the wide-spread months.

| | Energy | When it runs | Prize |
|---|---|---|---|
| **Hot water** | ~940–1200 kWh/yr | all year | **~€93/yr** — **€78 of it in Mar–Oct** |
| Space heating | 940 kWh/winter | Nov–Mar only | **~€33/winter** |

**Correction:** an earlier estimate put the space-heating emulator at
€60–100/winter. That applied recent *wide* spreads to heating energy — but
heating does not run in those months. Against the spreads actually present
during the heating season the figure is **~€33/winter**.

## What to change, in order

### 1. Run the DHW control year-round — especially March to October
**~€78/yr, no hardware, biggest single win.** 85 % of the hot-water prize sits
outside the heating season, and that is precisely when the control has been off
or mistargeted. Nothing else on this list comes close.

### 2. Replace the two fixed search bands with one adaptive search
**Required to make (1) work.** The bands (`18:00→06:30` and `12:00→18:00`) are
correct for deep winter, where the cheap hours are 01–04, and wrong from March
onward, where they move to 10–13. Rather than switching bands by season, search
the **cheapest 2.5 h anywhere between now and the next draw deadline**. That
adapts automatically and removes the seasonal assumption entirely.

### 3. One pre-evening fill using Ordered (SG Ready state 4 = 60 °C)
**No register change** — state 4 already commands 60 °C; leave Komfort at 55 and
the ECO floor at 40. Fire it once in the cheap window before the evening draw.
Measured effect on evening draws breaching the 40 °C floor:

| | fill to 55 °C | fill to 60 °C |
|---|---|---|
| Nov–Dec 2025 | 14 of 46 | **6 of 46** |
| August 2026 | 3 of 11 | **0 of 11** |
| March 2026 | 2 of 19 | 2 of 19 |

Consistently helps, never sufficient alone — roughly 11–13 % of evening draws
exceed the tank's usable band whatever the fill. Check the mixing valve is set
for 60 °C at the tap first.

### 4. Price-gate every raise
37 % of expensive-hour raises in August fired with the tank already at 50–55 °C
— pure waste. Refuse any Comfort raise above roughly the 40th price percentile
unless the tank is genuinely near the floor.

### 5. Cut the heating curve ~1 K
**Free, ~€15–20/winter, independent of all the above.** Register 1501:
215 → 205. The house ran above 22 °C for 44 % of last winter against a 21.5 °C
setpoint. Also lifts COP slightly by lowering flow temperature.

## What not to bother with

- **The ECO floor (40 °C)** — it is doing its job; a low floor is what keeps the
  pump passive. Leave it.
- **The 46 °C safety threshold** — never fired once in the record. Not a problem.
- **Elaborate winter optimisation** — the Nov–Feb prize is €14. Complexity there
  cannot repay itself.

## The emulator, honestly

At **~€33/winter** against ~€55 of parts plus the build, payback is roughly two
winters on parts alone. It remains a sound and interesting build — the parts are
ordered, the design is verified, and it is the only thing here that gives
*continuous* control rather than on/off — but it is no longer the headline
economic case. **The DHW software work is worth about three times as much and
costs nothing.** Do items 1–4 first; then build the emulator because it is worth
building, not because it is where the money is.
