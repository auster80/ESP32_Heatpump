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
| 1 | **39.2 Ω 0.1 % 25 ppm** metal film | `R1`, the permanent bias. E96 value nearest 39 Ω |
| 1 | **90.9 Ω 0.1 % 25 ppm** metal film | `R2`, shorted by `K2`. E96 nearest 91 Ω |
| 2 | 2N7000 small-signal MOSFET | relay drivers |
| 2 | 1N4148 diode | flyback across each relay coil |
| 2 | 1 kΩ, 2 × 10 kΩ resistors | gate drive and I²C pull-ups |
| 1 | 1000 µF 16 V electrolytic | bulk on the 5 V rail — not optional (§3.5) |
| 5 | 100 nF ceramic | decoupling, one per active part |
| 1 | 5 V 1 A supply | Class II / double-insulated, floating output (§3.5) |
| — | Enclosure, DIN terminal blocks, hookup wire | |

`R1` and `R2` in series give 130.1 Ω, which is the KTY setting; `K2` shorting
`R2` leaves 39.2 Ω for PT 1000. Exact values do not matter much — the
calibration in §3.6 fits what is actually fitted.

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
