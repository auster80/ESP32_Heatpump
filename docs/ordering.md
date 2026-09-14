# What to order

One build of the outdoor-sensor emulator described in
`virtual-outdoor-sensor.md`. Nothing here depends on knowing whether the AFS 2
is PT 1000 or KTY — §3.6 makes the board work with either and identify itself
once connected.

## Core

| Qty | Part | Package | Note |
|---|---|---|---|
| 1 | ESP32 dev board (ESP32-WROOM-32 DevKitC or similar) | module | Anything ESPHome supports |
| 1 | **AD5272BRMZ-100** — 100 kΩ, 1024-tap I²C digital rheostat | MSOP-10 | **Needs a breakout adapter** — see below |
| 1 | MSOP-10 → DIP breakout adapter | — | Order two; the first one is practice |
| 1 | **ISO1540D** — bidirectional I²C isolator | SOIC-8 | Plus a SOIC-8 breakout |
| 1 | **B0505S-1W** — isolated 5 V/5 V DC-DC | SIP-4, through-hole | |
| 1 | **G6K-2P-Y DC5** — DPDT signal relay, 5 V coil | through-hole | `K1`, the bypass. **Must be non-latching** |
| 1 | **G6KU-2P-Y DC5** — DPDT *latching* signal relay, 5 V coil | through-hole | `K2`, the bias select |
| 1 | **NE555** in DIP-8 (or TPL5010 + SOT-23-6 breakout) | DIP-8 | Hardware watchdog. The 555 is far easier to hand-build |

## Passives

| Qty | Part | Note |
|---|---|---|
| 1 | **39 Ω metal film, 1 %, ≤100 ppm/K** | `R1`, the permanent bias. Anything 36–47 Ω is fine — see below |
| 1 | **91 Ω metal film, 1 %, ≤100 ppm/K** | `R2`, shorted by `K2`. Anything 82–100 Ω is fine |
| 2 | 2N7000 small-signal MOSFET | relay drivers |
| 2 | 1N4148 diode | flyback across each relay coil |
| 2 | 1 kΩ, 2 × 10 kΩ resistors | gate drive and I²C pull-ups |
| 1 | 1000 µF 16 V electrolytic | bulk on the 5 V rail — not optional (§3.5) |
| 5 | 100 nF ceramic | decoupling, one per active part |
| 1 | 5 V 1 A supply | Class II / double-insulated, floating output (§3.5) |
| — | Enclosure, DIN terminal blocks, hookup wire | |

`R1` and `R2` in series give ~130 Ω, the KTY setting; `K2` shorting `R2` leaves
~39 Ω for PT 1000.

## Nothing here needs a precision resistor

An earlier draft of this list demanded 39.2 Ω and 90.9 Ω at **0.1 %**, which is
an E96 value in a tolerance that is genuinely hard to source in Europe as an
axial through-hole part. That requirement was wrong and has been removed. It
made the whole order hinge on one line item for no benefit.

The bias resistor's absolute value is **fitted, not trusted**: `fit_shunt()`
recovers it from readings of the pump's own outdoor register (§3.6). So its
tolerance is irrelevant — what the part *is* matters, not what the label says.
Measured against the model:

| Part actually fitted | Fit recovers | RMS | Sensor identified |
|---|---|---|---|
| 39.2 Ω (0.1 %) | 38.3 Ω | 0.088 K | pt1000, 7× margin |
| 39 Ω E24 (1 %) | 37.9 Ω | 0.089 K | pt1000, 6× margin |
| 43 Ω (10 % high) | 42.0 Ω | 0.076 K | pt1000, 9× margin |
| 47 Ω (20 % high) | 45.7 Ω | 0.122 K | pt1000, 5× margin |

A part 20 % away from nominal still works. What would *not* work is assuming a
nominal value and skipping the calibration: on a 43 Ω part, predicting unseen
points from the fitted model is accurate to **0.156 K**, against **0.96 K** if
you assume 39.2 Ω. Fitting is what buys the accuracy; tolerance never did.

**Drift is the only resistor property that matters here**, and 39 Ω is small
enough that it barely matters either. Over a 20 K swing inside the box:

| Grade | Drift | As sensor error |
|---|---|---|
| 0.1 %, 25 ppm/K | 0.020 Ω | 0.005 K |
| 1 %, 50 ppm/K | 0.039 Ω | 0.010 K |
| 1 %, 100 ppm/K | 0.078 Ω | 0.020 K |
| carbon film, 250 ppm/K | 0.195 Ω | 0.051 K |

Ordinary 1 % metal film is typically 50–100 ppm/K and costs nothing. Specify
that and buy it anywhere.

This is a property of the topology, not a lucky escape: §3.2 puts the
imprecise parts in a high-impedance parallel leg and calibrates the rest
against the pump. The same argument already excused the rheostat's ±1 % (and
the ±20 % of the DIP alternative). It excuses the bias resistors too.

Roughly €55 plus the enclosure.

## Two decisions worth making before you click buy

### 1. Packages: are you happy soldering MSOP-10?

The AD5272 is only made in MSOP-10 and TSSOP. On a breakout adapter it is
manageable with a fine tip and flux, but it is the hardest joint in the build.

**If you would rather stay entirely through-hole**, substitute the
**MCP41100-I/P** (100 kΩ, 256 taps, SPI, **PDIP-8**). It works here: 256 taps
gives 0.36 K worst case across a ±6 K range, which is fine for a heating curve.
One catch — it is a **±20 % end-to-end** part against the AD5272's ±1 %, and
§3.6 warns that a loose full-scale bound lets the wrong sensor characteristic
mimic the right one. The fix is one meter reading: measure `A`–`W` at a known
tap on the bench, pass the measured value as `full_scale_ohms`, and let the
calibration fit only the bias. Identification then works normally.

### 2. The excitation check is still outstanding

The AD5272 tolerates 5.5 V across its terminals. Your schematic shows the
WPM3i's analog rail is **+5 V**, so this almost certainly passes — but it is
measured, not assumed (§7.2 step 6).

If it comes back above 5.5 V, swap the rheostat for an **AD5290** (±15 V,
256 taps) and change nothing else. At ~€8 it is cheap insurance to add to the
same order if you would rather not wait for a second delivery.

## The one thing not to get wrong

**`K1` must be non-latching.** It is the fail-safe: losing power has to drop it
so the real AFS 2 returns to the pump. A latching relay there would hold the
emulator in circuit through a power cut, which is exactly the failure the
design exists to prevent. `K2` is the opposite case — latching is preferred,
because it draws no standing current and keeps its setting through a reset.

---

# Breadboard variant

Everything above can be swapped for through-hole parts, and one substitution
unlocks the rest.

## The unlock: go SPI

The AD5272 is I²C, and **I²C needs bidirectional isolation** — the data line is
driven from both ends. Bidirectional isolators (ISO1540, ADuM1250) are SMD
only, so the I²C route forces at least one surface-mount part.

Writing a tap to a digital potentiometer is **one-directional**: clock, data,
chip-select, nothing coming back. An SPI part therefore needs only three
unidirectional isolated channels, and those are available as ordinary **DIP-8
optocouplers**. Choosing an SPI rheostat makes the whole build through-hole.

## Substitutions

| Instead of | Use | Why |
|---|---|---|
| AD5272BRMZ-100 (MSOP-10, I²C) | **MCP41100-I/P** — 100 kΩ, 256 taps, SPI, **PDIP-8** | Breadboards directly. Verified below |
| ISO1540 (SOIC-8) | **3 × 6N137** (DIP-8 optocouplers) | Three write-only channels, not a bidirectional bus |
| G6K-2P / G6KU-2P | **2 × Omron G5V-2-DC5** — DPDT, 0.3" DIP footprint, 5 V coil (~40 mA) | Drops straight into a breadboard. Use non-latching for both while prototyping; `K2` latching is an optimisation, not a requirement |
| ESP32 DevKitC (25.4 mm wide) | **ESP32-PICO-KIT** (20.3 mm) | Leaves two free columns each side instead of one |

The NE555, B0505S-1W, 2N7000, 1N4148, and all passives are already through-hole.

## Does the DIP part actually work?

Yes — and the higher wiper resistance barely registers, because the rheostat
sits in the high-impedance parallel leg:

| Part | Shift range at 0 °C | Safe taps | Worst step |
|---|---|---|---|
| AD5272, 1024 taps, 35 Ω wiper | −7.3 … +29.7 K | 60–1023 | 0.090 K |
| MCP41100, 256 taps, 52 Ω wiper | −7.3 … +29.5 K | 15–255 | 0.359 K |
| MCP41100, 256 taps, **125 Ω** worst-case wiper | −7.3 … +29.1 K | 15–255 | 0.356 K |

0.36 K per tap against a heating curve is not a limitation.

## The ±20 % tolerance turns out to help

The MCP41100 is ±20 % end-to-end against the AD5272's ±1 %, and §3.6 warns that
a loose full-scale bound lets the wrong sensor characteristic mimic the right
one. The answer is to stop fitting it: **measure `A`–`W` once with a meter at a
known tap**, pass the measured value as `full_scale_ohms`, and let the
calibration fit only the bias.

That leaves one free parameter instead of two, and identification gets *better*
rather than worse. With a part 18 % high and the scale measured and fixed, five
observations gave a **27.7× margin** at **0.022 K rms** — against 10.4× and
0.048 K when both parameters were fitted.

## USB powers the bench build

No external supply is needed until the box leaves the desk. Budget at 5 V:

| Draw | Steady | Wi-Fi TX peak |
|---|---|---|
| ESP32-PICO-KIT-1 | ~120 mA | ~300 mA |
| 2 × G5V-2 coils, both energised | ~70 mA | ~70 mA |
| NE555 + MCP41100 | ~10 mA | ~10 mA |
| **Total** | **~200 mA** | **~380 mA** |

Inside USB 2.0's 500 mA, with margin. Four conditions:

1. **Drive the relay coils from the board's 5 V pin, not 3.3 V.** They are 5 V
   coils, and 70 mA through the onboard LDO would be wrong twice over.
2. **Fit the 1000 µF bulk capacitor on the bench too.** The Wi-Fi peak against a
   thin cable's resistance is exactly the droop that resets the ESP32 and makes
   K1 chatter (§3.5). Use a short, decent cable.
3. **Check the board's connector** before buying a cable — Espressif devkits of
   this generation are often micro-USB rather than USB-C.
4. The earthed-laptop-USB hazard in §3.5 does **not** apply on the bench: with
   no pump connected there is no second ground domain to loop with. It starts
   mattering the moment anything is wired to X2.

## Skip the isolation while you are on the bench

The optocouplers and the B0505S only matter once the box is wired to the WPM.
For bench work there is no second ground domain, so leave them out and add them
for the install.

A useful bench rig is small:

- a **1 kΩ resistor** standing in for the AFS 2 (tolerance irrelevant, just measure it) (a 10-turn trimmer or a
  decade box is better — it lets you sweep "weather")
- a meter across the nodes that will become `X2 T(A)` and `X26`
- compare what it reads against `ShuntEmulator.presented_ohms()` for the tap
  you set

That validates the maths, the SPI writes, the relay logic and the watchdog
without the heat pump being involved at all. Only after that does anything get
connected to `X2`.

## Breadboard shopping list

ESP32-PICO-KIT · MCP41100-I/P · 2 × Omron G5V-2-DC5 · NE555 (DIP-8) ·
2 × 2N7000 · 2 × 1N4148 · 39 Ω and 91 Ω 1 % metal film · 1 kΩ 1 % (sensor
stand-in, measure it) · 1 kΩ + 2 × 10 kΩ · 1000 µF 16 V · 5 × 100 nF · 5 V 1 A supply ·
breadboard and jumpers.

Add for the install: 3 × 6N137 · B0505S-1W · enclosure and terminal blocks.

One note on firmware: neither the AD5272 nor the MCP41100 has a ready-made
ESPHome component, so the tap write is a small custom piece either way. SPI is
the easier of the two to drive from a lambda.


## The isolated converter needs a minimum load

Worth knowing before ordering, because it adds two parts and is independent of
which converter you buy.

The rheostat section draws almost nothing — a milliamp or two. Unregulated SIP
converters specify load regulation only down to roughly **10 % of rated load**;
below that the output climbs well above nominal. On a 1 W part that threshold is
about 20 mA, and we are two orders of magnitude under it. A 5 V rail sitting at
6 V would put the MCP41100 past its 5.5 V supply maximum.

Fit a **270 Ω 0.5 W** bleed resistor across the isolated output (≈18 mA, ≈90 mW)
and a **5.1 V 0.5 W zener** as a clamp. Confirm the value against the specific
converter's minimum-load line.

## What the isolation barrier actually has to hold

**1 kV is enough. Do not open a third shop for a 1.5 kV part.**

Both sides of the barrier are already SELV — the ESP32 side behind the Class II
supply's mains isolation, the pump side behind the WPM's own. The barrier here
is **functional**: it breaks a ground loop and keeps ESP32 switching current out
of the measurement reference (§3.7). It is not protective separation and must
not be relied on as such; if mains ever reaches the WPM's SELV rail, that unit's
own safety isolation has already failed and this converter is not the thing
standing between you and it.

One consequence to be aware of rather than fix: 6N137 optocouplers are typically
2.5 kV, so a 1 kV converter becomes the weakest element and sets the barrier's
figure. That is fine for functional isolation and would not be if we were making
a safety claim.
