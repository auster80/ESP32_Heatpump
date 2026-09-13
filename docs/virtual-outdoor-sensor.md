# Virtual outdoor sensor: an Ngenic-style controller for any heat pump

Ngenic Tune makes almost any hydronic heat pump price-aware without touching
its controller: a small box sits between the outdoor sensor and the heat
pump and feeds the pump a *manipulated* outdoor temperature. The pump keeps
running its own weather-compensated heating curve; it simply believes it is
colder (heat more, now, while electricity is cheap) or milder (coast on the
house's thermal mass while it is expensive). This document designs the same
thing for this repository: the hardware that reads and replaces the sensor
signal, and the control logic that learns how the house responds and plans
the manipulation from Tibber prices.

Hot water is left out on purpose: you already schedule it by price, and the
outdoor sensor has no influence on it.

## 1. Do you need the hardware at all?

The sensor trick is only necessary when the heat pump has no digital way to
shift its curve. Many do, and then the same control logic drives a register
instead of a resistor and nothing needs soldering:

| Heat pump family                        | Local interface                          | Curve shift written as                 |
|-----------------------------------------|------------------------------------------|----------------------------------------|
| NIBE S-series                           | Modbus TCP built in (menu 7.5.9)         | heating offset register                |
| NIBE F-series                           | Modbus 40 accessory or RS485 hack        | heating offset register                |
| Stiebel Eltron / Tecalor                | ISG web, Modbus TCP                      | room set / curve offset                |
| Vaillant                                | eBUS via `ebusd`                         | `Hc1HeatCurve` / room set              |
| Viessmann                               | Optolink via `vcontrold`, `OptolinkP300` | `NiveauHK` (curve level)               |
| Bosch / Buderus / Junkers / IVT         | EMS bus via `EMS-ESP`                    | `hc1 offset` / `desinftemp`            |
| Panasonic Aquarea                       | CN-CNT via `HeishaMon`                   | heating curve shift (`SetCurves`)      |
| Mitsubishi Ecodan                       | CN105 via `ecodan-ha-local`              | flow temperature offset                |
| Daikin Altherma                         | P1/P2 via `P1P2MQTT`                     | leaving water offset                   |
| Alpha Innotec / Novelan / Siemens Novelan| Luxtronik TCP                            | `Temperatur_Heizung_Verschiebung`      |

If your pump is on this list, use the `modbus` or `mqtt` backend (or a small
adapter to the tool named) as the actuator and skip section 3. The control
logic in section 4 is identical; only the last hop changes.

If it is not, or you want something that is guaranteed independent of the
pump's firmware, build the emulator.

## 2. Preconditions and safety

Read these before wiring anything into the heat pump.

1. **Separate climate sensor only.** Manipulate the outdoor *climate* sensor
   that feeds the heating curve (NIBE BT1, Vaillant VR10, Viessmann outdoor
   sensor, ...). Never touch a sensor inside the outdoor unit: air-source
   units use those for defrost and compressor protection. If the pump derives
   its curve from the outdoor unit's own sensor, this approach is unsafe for
   that pump; use SG Ready or a digital interface instead.
2. **Identify the sensor.** Disconnect it, measure its resistance and compare
   with the real temperature: about 10 kΩ at 25 °C / 33 kΩ at 0 °C means a
   10 kΩ NTC (beta ≈ 3977; NIBE, Bosch/IVT, Viessmann, Vaillant), about
   1000 Ω at 0 °C means PT1000 (Stiebel Eltron, some Alpha Innotec). Other
   NTC values exist (2 kΩ, 5 kΩ, 12 kΩ, 20 kΩ); the beta model in
   `sensors.py` handles them once `r25`/`beta` are set.
3. **Measure the excitation.** With the sensor disconnected, measure the
   voltage the pump applies to the sensor terminals and, with a resistor of
   known value connected, the current. Most controllers use 3.3 V or 5 V
   through a pull-up; a few use 12 V or a pulsed current source. A digital
   potentiometer must stay inside its supply rails (5.5 V for the AD5272
   family), so anything above 5 V needs the relay ladder (option B).
4. **Keep the pump's own limits.** Never present less than −30 °C or more
   than +35 °C, and never move more than a configurable `max_shift` (8 K is
   plenty) from the real value. Presenting a very warm temperature switches
   many pumps into summer mode and stops heating entirely; this is the
   `block` equivalent and must obey the same duration limits as the SG Ready
   scheduler.
5. **Fail safe by construction.** The real sensor must reach the heat pump
   whenever the emulator is unpowered, crashed, or has not heard from the
   controller for a while. This is a relay, not software.
6. **Frost protection and DHW are unaffected**, but check the pump's
   "heating season" logic: if it averages the outdoor temperature over 24 h to
   decide whether heating is allowed, long positive shifts in autumn can keep
   it in heating mode, and long negative ones can stop heating early.

## 3. Hardware

### 3.1 The topology

The real AFS 2 **stays in the measurement path**. A digital rheostat in
parallel pulls the presented resistance down (colder); a small fixed resistor
in series biases the whole range up (warmer) so both directions are reachable.

```
  X2  T(A) o───────┬──────────[ K1 · NO ]──────┬──── R_bias 39R 0.1% ────┐
                   │                            │                         │
                   │                            └──── AD5272 rheostat ────┤
                   │                                   (100k, 1024 taps)  │
                   │                                                      │
                   └──────────[ K1 · NC ]─────────────────────────────────┤
                                                                          │
                                                          real AFS 2 ─────┤
                                                        (north wall)      │
  X26 GND  o──────────────────────────────────────────────────────────────┘
```

K1 de-energised (NC) = the raw AFS 2 straight to the pump, exactly as today.
K1 energised (NO) = bias + rheostat in circuit.

### 3.2 Why not synthesise the resistance outright

An earlier draft of this document proposed a binary-weighted resistor ladder
switched by nine relays. That was wrong, for a reason worth recording:

- Its LSB was **1 Ω**, and it put **nine relay contacts in series with the
  measurement**. Signal-relay contact resistance is 50–100 mΩ each and drifts
  at dry-circuit currents, where there is no wetting current and contacts
  oxidise. The error source sat in the same path as the signal, at the same
  order as the LSB.
- Nine latching relays means eighteen coil drives, a large board and many
  joints, to control a span of about 150 Ω.

The shunt puts the imprecise, active part in a **high-impedance parallel path**
where its error is divided down. A 1 % rheostat tolerance becomes ≈ 0.13 K on
a 4 K shift, and it is a fixed gain error that calibrates out by measuring the
part once. Contact resistance disappears from the problem: the only contact in
the measurement path is K1, and K1 is either fully in or fully out.

It also removes an entire subsystem. Because the real sensor is still in
circuit, **the emulator never has to measure the outdoor temperature** — real
weather passes through by itself. No ADS1115, no divider, no second sensor,
and the pump keeps the sensor it was commissioned against.

### 3.3 Closing the loop without a second sensor

The controller does need the *true* outdoor temperature to pick a tap, because
a parallel shunt scales resistance rather than adding kelvin. It gets it from
the pump itself: read the manipulated value from input register 506
(**read-only — no write endurance cost**) and invert the known shunt.

`ShuntEmulator.recover_real_c()` does this and is accurate to **±0.04 K** even
with register 506 quantised to 0.1 °C.

### 3.4 Components

| # | Part | Why |
|---|---|---|
| 1 | **ESP32** dev board (ESPHome) | control, Wi-Fi/MQTT |
| 2 | **AD5272BRMZ-100** — 100 kΩ, 1024-tap I²C digital rheostat | the shunt. ±1 % end-to-end, ~35 Ω wiper, 5.5 V max across terminals |
| 3 | **39 Ω + 91 Ω, 0.1 % 25 ppm** | series bias. `K2` shorts the 91 Ω: 39 Ω for PT 1000, 130 Ω for KTY (§3.6) |
| 4 | **ISO1540** I²C isolator + **B0505S-1W** isolated DC/DC | floats the rheostat section at the pump's X26 potential. Not optional |
| 5 | **DPDT signal relay** (Omron G6K-2P) ×2 + drivers + flyback diodes | `K1` the bypass (NC = real sensor); `K2` the bias select, latching preferred |
| 6 | **TPL5010** (or NE555 monostable) | hardware watchdog holding K1 in only while the ESP32 heartbeats |
| 7 | **5 V 1 A supply**, 1000 µF bulk cap, enclosure, terminal blocks | see §3.5 — the choice interacts with the isolation |

Roughly €40. Note what is **not** in the list: no ADC, no second temperature
sensor, no resistor ladder, no latching relays.

### 3.5 Powering it

Budget, worst case: the ESP32 peaks around 350 mA at 3.3 V while the Wi-Fi
radio transmits, the G6K-2P coil draws ~40 mA, and the B0505S needs its
quiescent plus the few milliamps the rheostat section actually uses. **5 V at
1 A** is comfortable with headroom; 500 mA is cutting it close on Wi-Fi peaks.

**Is there a SELV supply on the pump?** Yes, and it is the wrong one. Terminal
block **X2** carries `+`, `⊥`, `L`, `H` — the CAN bus that powers the FEK
remote, fed from an internal supply module (`X29` mains in, `X30`/`X31` CAN
out). Three reasons not to hang the emulator on it, the third decisive:

1. **No rating is published.** The manual gives the terminal but no voltage and
   no current budget. It is sized for an FEK: an LCD, a knob and a few buttons.
2. **Stiebel do not use it for their own gateway.** The ISG connects to `H`,
   `L` and `⊥` only, and the manual says plainly *"Die Spannungsversorgung des
   ISG erfolgt nicht über die Wärmepumpe."* If the bus rail could not carry
   their own small gateway, it will not carry an ESP32 whose radio pulls
   350 mA peaks.
3. **Its return is `⊥`, which is X26 — the exact node the AFS 2 is measured
   against.** Drawing Wi-Fi current pulses through that ground modulates the
   reference of the measurement we are trying to control to a fraction of a
   kelvin. A PT 1000 at 0.1 °C resolution is 0.39 Ω; this is a sub-millivolt
   measurement and we would be injecting hundreds of milliamps of switching
   noise into its return path. That is precisely what the isolation in §3.4
   exists to prevent, so powering from the bus would undo it.

Browning out that rail would also disturb the FEK, which is a control the
household actually uses.

Measure the `+` rail's voltage anyway while the covers are off (§7.2) — it is
free information, and a genuinely low-power design that never transmits could
revisit this. For an ESP32 with Wi-Fi, use one of the two sources below.

Two sensible sources:

**A. A USB wall-wart into a socket near the indoor unit.** Simplest, and the
floating output of a double-insulated (Class II) supply is exactly what this
design wants — see the grounding note below. Needs a socket within reach.

**B. A DIN-rail 5 V supply fed from the `Steuerspannung` 230 V control feed**
(`3×1,5 mm²`, `1×B16A` on this house's schematic). Tidiest permanent install:
the emulator is powered whenever the pump is, and no separate socket or visible
wall-wart. It is electrician work, needs its own fuse or MCB, and must not
compromise the pump's own supply.

Either way the emulator stays on its own supply — **do not** try to steal power
from the sensor input or any other WPM terminal.

**Grounding.** The ESP32 side must remain a *separate ground domain* from the
pump's X26; bonding them defeats the point of the ISO1540 and B0505S. A Class
II supply with a floating output keeps it separate by construction. The
isolator also covers the development case where the ESP32's USB is plugged into
an earthed laptop, which would otherwise tie earth to X26.

**Losing power is a non-event, by design.** K1 drops, the real AFS 2 returns,
the pump carries on exactly as it does today. A cheap supply failing costs a
heating optimisation, not a heating system.

**A sagging supply is the real risk, and it is not the same thing.** Brown-outs
at Wi-Fi peaks reset the ESP32 in a loop, and a naive build would then chatter
K1 between bypass and emulate — the pump would see its outdoor temperature jump
several kelvin every few seconds, which at best confuses the curve and at worst
trips a plausibility check. Two defences, both required:

1. **1000 µF bulk on the 5 V rail** plus 100 nF decoupling at each chip.
2. **A firmware hold-off** (§4): never energise K1 on boot. Come up in bypass,
   and only pull the relay in after the controller has been connected and
   holding a valid target for a settling period. A boot loop then parks
   permanently in bypass, which is the safe state, instead of oscillating.

### 3.6 One circuit for both sensors, calibrated by the pump

The topology does not care which sensor is fitted. The shift a given tap
produces scales as `R_sensor² / (R_pot · dR/dT)`, and for these two
characteristics that ratio is **a constant 1.32 across the whole range**:

| Rheostat | PT 1000 shift | KTY shift | ratio |
|---|---|---|---|
| 100 kΩ | +2.6 K | +2.0 K | 1.31 |
| 50 kΩ | +5.2 K | +4.0 K | 1.32 |
| 20 kΩ | +12.6 K | +9.6 K | 1.32 |
| 10 kΩ | +24.1 K | +18.2 K | 1.32 |

So the same AD5272-100 serves both. Only the series bias differs, because it
has to buy the same *kelvin* of warm range out of a sensor with 3.7× the
resistance slope: **38 Ω for PT 1000, 129 Ω for KTY**.

**Make the bias switchable.** `R1` = 39 Ω 0.1 % permanently in circuit, `R2` =
91 Ω 0.1 % in series with it, shorted by a second signal relay `K2`. K2 open
gives 130 Ω (KTY), K2 shorting gives 39 Ω (PT 1000). Prefer a latching relay:
no standing coil current, and the setting survives a reset. One relay and one
resistor buy a board that does not need to know the sensor before it is built.

#### The pump is the reference

Once connected, the box can identify its own sensor and calibrate its own
parts, because the pump reports what it sees. One observation is a pair of
readings of input register 506 taken close enough together that the weather has
not moved:

1. K1 de-energised — the pump reads the raw sensor. That is the **true**
   outdoor temperature, and it fixes `R_sensor` under each hypothesis.
2. K1 energised at a known tap — the pump reads the shunted value.

Each hypothesis predicts a different second reading, and they are far apart. At
a true 5 °C with the rheostat at 20 kΩ, PT 1000 predicts **+1.36 °C** and KTY
**−2.16 °C** — 3.5 K apart against a register quantised to 0.1 °C, a margin of
about 35×. `identify_sensor()` does this; `fit_shunt()` does the least-squares
fit behind it.

#### It calibrates more than the sensor

The same fit recovers the **series bias and the rheostat's true full scale** —
exactly the two values the datasheet only bounds. §3.2 noted that the AD5272's
±1 % tolerance costs about 0.13 K on a 4 K shift; fitting it against the pump's
own readings removes that, and removes the bias resistor's tolerance with it.
In a worked example with a KTY sensor, the bias 4 % high and the rheostat 1.2 %
low, seven observations identified the sensor with a **10.4× margin**, fitted to
**0.048 K rms**, and recovered the bias to within 1.8 Ω.

Two honest limits:

- **Three observations minimum.** Fitting two part values costs two degrees of
  freedom, so one or two readings cannot separate the candidates;
  `identify_sensor()` refuses rather than returning a confident-looking guess.
  A single tap change *is* decisive as a field check, but only against assumed
  nominal parts.
- **Keep the full-scale bound tight** (±5 % of nominal is the default). Allow
  ±20 % and the wrong characteristic can mimic the right one by moving the full
  scale, and the discrimination collapses.

Spread the observations over a few days of different weather and different
taps. Confidence is reported as a ratio — how many times worse the runner-up
fitted — because residuals scale with how hard the taps were driven.

### 3.7 What it achieves

Measured against the model, PT1000, 39 Ω bias, 100 kΩ rheostat:

| Real outdoor | Shift range | Tap accuracy |
|---|---|---|
| −19 °C | −7.6 … +10.9 K | better than 0.05 K |
| 0 °C | −7.3 … +29.7 K | better than 0.05 K |
| +10 °C | −7.1 … +39.5 K | better than 0.05 K |

The cold direction is bounded by the −30 °C floor rather than by the hardware.
`ShuntEmulator.safe_taps()` enforces that window, because at the closed end the
rheostat approaches its wiper resistance and would short the sensor — a
`FÜHLERBRUCH E 71` to the pump.

`max_shift` in the controller should still be set far tighter (2 K to start).

### 3.8 Safety

- **K1 is the fail-safe**, not software. Power loss, firmware hang, or a stale
  controller drops the relay and the real AFS 2 returns.
- The watchdog must be **hardware**. A timer inside the same firmware that
  might hang is not a watchdog.
- **Isolation is mandatory.** The rheostat sits across the pump's SELV sensor
  input. Tying an earthed ESP32 ground to X26 risks a ground loop through the
  measurement or worse. €8 of parts.
- Before the AD5272 will move its wiper it needs the control register written
  once after boot (`0x1C 0x02`); it powers up frozen.
- Verify the excitation stays within the AD5272's 5.5 V terminal rating
  (§7.2 step 5). If the WPM drives more than that, this topology is out.

## 4. Firmware

`firmware/esphome-outdoor-sensor-emulator.yaml` is an ESPHome sketch for
option A: it publishes the real outdoor temperature, subscribes to a target
temperature, writes the AD5272 tap, and drops the bypass relay when no
heartbeat arrives for 20 minutes or the target is out of bounds. It is
written against the datasheet and ESPHome documentation but has not been
run on hardware; treat it as a starting point and verify the I²C frames
with a logic analyser before connecting the pump.

Two rules the sketch must enforce beyond what it does today:

- **Boot into bypass.** K1 stays de-energised until MQTT is connected, a
  retained `target_c` has arrived, and a settling period (60 s is plenty) has
  elapsed. This is what turns a brown-out boot loop into a harmless permanent
  bypass rather than a relay chattering against the pump's sensor input
  (§3.5).
- **Rate-limit the relay.** Never toggle K1 more than once a minute, whatever
  the controller asks for.

MQTT topics (all under `heatpump/outdoor/`):

| Topic         | Direction  | Payload                                    |
|---------------|------------|--------------------------------------------|
| `real_c`      | emulator → | measured outdoor temperature, every 60 s   |
| `target_c`    | → emulator | temperature to present (retained)          |
| `heartbeat`   | → emulator | any payload, at least every 10 min         |
| `state`       | emulator → | `bypass` or `emulating <tap>`              |

## 5. Control logic

### 5.1 What "learning" has to learn

The heat pump already closes the outdoor loop: its curve raises the supply
temperature when it gets colder. What it does not know is the room. A
weather-compensated pump therefore behaves, seen from the room, like a
proportional controller pulling the indoor temperature towards the
equilibrium implied by its curve. A shift of the outdoor reading moves that
equilibrium. That gives a deliberately small model (`curve.py`):

```
dT_in/dt = c − a·T_in + b·shift_eff + d·T_out        (rates per hour)
shift_eff follows shift with a first-order lag `filter_minutes`
```

- `a` is the pull-back rate (1/h); `1/a` is the house time constant, typically
  10–40 h for floor heating in an insulated house.
- `b` is the warming rate per K of shift; it encodes the curve slope, the
  emitter size and the house mass together.
- `c/a` is the equilibrium room temperature at zero shift (what the curve is
  tuned to).
- `d` is the residual outdoor influence and is ≈ 0 when the curve is well
  tuned; if it is clearly non-zero, the curve slope is off and you may as
  well fix that in the pump's menu.
- `filter_minutes` is the pump's outdoor smoothing. NIBE calls it "dämpad
  utetemperatur"; many pumps average over 1–3 h. It is a pump setting or a
  measurement (watch the supply set point after a step in the fake reading).

These are fitted by least squares from a CSV log (`curve-fit`) and can be
refined online with the recursive least-squares estimator in `learning.py`.
The controller's own price-driven shifts provide the excitation the fit
needs; one or two weeks of heating-season data with the default action set
identify `a` and `b` to about 10 %, as the tests with a simulated house
show.

For the cost side, electrical power is modelled as
`P = standby + g·max(0, T_limit − T_out) + p·shift_eff`, fitted from a
power meter or Tibber Pulse reading if available (`power_kw` column),
otherwise estimated from the pump's data sheet.

### 5.2 Planning

`plan_curve()` runs a dynamic programme over the price horizon (today and,
after 13:00, tomorrow) with the state (indoor temperature, effective shift)
and the allowed shifts as actions. It minimises

```
Σ price·P·Δt  +  comfort·(T − target)²·Δt  +  violation·(distance outside band)²·Δt
```

plus a terminal term that values heat left in the house at the mean price,
so the plan neither hoards nor dumps heat at the horizon. The comfort term
matters: a cooler room always loses less heat, so without it the cheapest
plan sits at the bottom of the band for ever. With it the planner deviates
from the target only where the price spread pays for it: pre-heating towards
the top of the band in cheap night slots and coasting through the morning
and evening peaks. Model error is handled by re-planning every slot from
the measured indoor temperature (receding horizon); the test suite shows a
25 % wrong model still holding the band within 0.4 K.

Run it against your real prices now:

```bash
tibber-heatpump-bridge curve-plan --indoor 21.3 --outdoor 2.0
tibber-heatpump-bridge curve-plan --indoor 21.3 --outdoor 2.0 --slots   # every 30 min
```

### 5.3 Runtime loop (next step, not yet implemented)

```
every planning slot (15–30 min):
    read indoor T (HA / MQTT / the pump's room sensor), real outdoor T (emulator)
    re-plan from the current state; take the first shift
    clamp: |shift| ≤ max_shift, presented value within [−30, 35] °C
    publish target_c = real − shift and a heartbeat
    append (time, T_in, T_out, shift, power) to the CSV log
    RLS update of the house model; log the residual
fail-safe:
    no indoor reading, stale prices, or a planner error → shift 0
    controller stops → emulator times out → relay bypass
```

Bootstrapping: start with the conservative default action set (−3 … +2 K)
and the default model, log for a week, run `curve-fit`, paste the result into
`[curve.model]`, then widen the actions.

### 5.4 Relation to the SG Ready scheduler

Both controllers can run side by side. SG Ready or Modbus modes are coarse
and immediate (block, boost); the curve shift is fine-grained and slow. A
sensible split for a house with floor heating: curve shifting for space
heating, the price scheduler for hot water and for hard blocks in extreme
price spikes.

## 6. This installation

Answered from the existing Home Assistant configuration and from the register
catalogue in the `Modbus Tool` project (`Modbus Doctor`), which was written
against this very heat pump.

1. **Heat pump model and interface.** A **Tecalor TTF 13 cool** (Stiebel
   Eltron rebrand) behind an **ISG plus** gateway, reachable at
   **`192.168.0.121:502`, unit ID 254** (Modbus TCP). Relevant holding
   registers:

   | Register | Meaning | Range | Persists? |
   |---|---|---|---|
   | 1501 | HC 1 comfort temperature (`Komforttemperatur HK1`) | 5…30 °C | parameter |
   | 1502 | HC 1 eco temperature (`ECO-Temperatur HK1`) | 5…30 °C | parameter |
   | 1503 | HC 1 heating curve rise (`Steigung Heizkurve HK1`) | 0…3 | parameter |
   | 1507 | Fixed value operation (`Festwertbetrieb`) | off / 20…70 °C | parameter |
   | 1509 | DHW comfort setpoint | 10…60 °C | parameter |
   | 4000 | SG Ready on/off | 0/1 | parameter |
   | 4001, 4002 | SG Ready inputs 1 and 2 | 0/1 | contact emulation |
   | 5000 | SG Ready operating state (read-only) | 1…4 | — |

   Section 1's table says a pump with this interface does not *need* the
   emulator. That is true but not the whole argument — see section 6.2.

2. **Sensor type and excitation voltage.** Still open, and still needed if the
   emulator is built. Measure at the WPM/ISG terminal block, never at a sensor
   inside the outdoor unit.

3. **Indoor temperature.** The FEK room unit, already exposed to Home
   Assistant as `sensor.tecalor_raumtemperatur_isttemperatur_fek`. The outdoor
   temperature the pump currently sees is input register 506.

4. **Coldest outdoor temperature to represent.** **−19 °C.** The house is in
   **The Hague**, where the design outdoor temperature is nowhere near that;
   −19 °C is deliberate headroom so the actuator never saturates at the bottom
   of the range, and it is what a single resistor pot covers if the emulator is
   built.

5. **Power reading.** Daily compressor energy exists
   (`sensor.tecalor_leistungsaufnahme_vd_heizen_tag` and `..._warmwasser_tag`),
   enough to fit `PowerModel` from daily totals but not for an instantaneous
   cost model. Whether an instantaneous power register exists on this
   controller is unverified.

### 6.1 Write endurance: the constraint that shapes the design

A holding register that holds a **parameter** — a setpoint, a curve rise — is
not a variable in RAM. It is stored in the controller's non-volatile memory,
which survives a finite number of write cycles. Controllers of this class
typically quote something on the order of 10⁵ writes per cell; a cell that is
rewritten past its rating stops holding its value, and on a heating controller
that means a dead board, not a graceful degradation.

The arithmetic is unforgiving. This bridge's `reapply_minutes` defaults to 15
and deliberately re-sends the current mode *even when it has not changed*,
because a relay may have rebooted. Against a register that is:

| Write cadence | Per day | Per year | 10⁵ cycles reached in |
|---|---|---|---|
| every tick (60 s) | 1 440 | 525 600 | ~10 weeks |
| every `reapply` (15 min) | 96 | 35 040 | ~3 years |
| on change only (~6/day) | 6 | 2 190 | ~45 years |

A naive `curve run` loop writing a heating-curve offset every price slot lands
in the middle row and destroys the controller inside the warranty period of
the *next* one.

**What the documentation actually says.** The official Tecalor/Stiebel ISG
Modbus manual (all 16 pages checked) documents function codes 06 and 16 for
holding registers and carries only a generic *"Sachschaden — Unsachgemäßer
Gebrauch kann zur Schädigung ... der Wärmepumpe führen"*. It gives **no**
write-cycle rating, no minimum write interval, and no EEPROM warning. The
frequently-quoted "max. 100 000 writes, otherwise the EEPROM may be
permanently damaged" figure circulating in search results is from an
**ebm-papst fan-electronics** Modbus guide, *not* from Stiebel Eltron — do not
cite it as a Tecalor specification. The exact memory technology and endurance
of the WPM board is therefore **unverified**; treat the limit as real and
unknown rather than as a number you can budget against.

**Consequences, already implemented in `backends/modbus.py`:**

- A non-volatile register is written **only when the value changes**. Repeated
  `apply()` of the same mode costs nothing.
- `volatile = true` marks targets that do *not* persist — coils, and the SG
  Ready input registers 4001/4002, which emulate contacts. Those are rewritten
  every tick so a rebooted device is repaired.
- `max_writes_per_day` is a hard per-address budget over a rolling 24 hours.
  When it is spent the write is refused and logged; the heat pump simply keeps
  its current setting, which is the safe direction.
- SG Ready (4000/4001/4002) is the preferred Modbus actuator over setpoint
  registers, because state 1–4 is a contact emulation rather than a stored
  parameter. **This is inference from what the registers represent, not a
  documented guarantee** — verify before relying on it, for example by writing
  4001 a few thousand times on a bench unit, or by asking Stiebel support.

### 6.2 Why the emulator is still the better design

The earlier reading of section 1 — "this pump has Modbus, so the hardware is
unnecessary" — misses the point of the sensor trick. The emulator is not a
workaround for a missing interface. It is a way to put the controller under
**external authority**:

- **It writes nothing.** A manipulated resistance costs zero write cycles. The
  constraint in section 6.1 disappears entirely instead of being managed.
- **It overrides rather than asks.** Writing 1501 negotiates with the Tecalor
  controller's own logic, which keeps its hysteresis, its blocking times, its
  own idea of what the curve means, and may clamp or ignore what you write.
  Feeding the curve a different outdoor temperature changes the input the
  controller reasons from, so its whole logic moves with you.
- **It is firmware- and vendor-independent.** It survives an ISG firmware
  change, a register renumbering, or replacing the pump with another brand.
- **It degrades safely.** Behind a fail-safe bypass relay, losing power or
  losing the controller returns the real sensor and the house heats normally.

The Modbus path is the faster one to a working system and needs no hardware;
the emulator is the one that actually delivers the Ngenic-style external
control this document set out to build. They are not exclusive — section 5.4
already suggests running both, and SG Ready over Modbus is a good coarse
actuator precisely because it is not a stored parameter.

### 6.3 Next step

1. Confirm SG Ready is enabled in the installer menu (register 4000).
2. Build the `curve run` loop against the **Modbus** path first, with the write
   guard on, to validate `plan_curve()` against the real house.
3. Answer question 2 (sensor type and excitation) and build the emulator once
   the control logic is proven, moving the last hop off Modbus entirely.

## 7. Hardware implementation plan for this house

### 7.1 What the Tecalor documentation already settles

From the TTF / TTF cool installation manual and the electrical schematic for
this house, so none of this needs measuring:

| | |
|---|---|
| Sensor | **AFS 2** outdoor sensor, supplied in the box with the unit |
| Location | North or north-east wall, ≥ 2.5 m above ground, ≥ 1 m from windows and doors, free to the weather but out of direct sun. The schematic says *"Zur Nordseite des Gebäudes"* |
| Terminals | **X2 `T(A)`** for the sensor, **X26** (`Masseblock für Kleinspannung`) for its ground |
| Voltage class | `Sicherheitskleinspannung` — SELV. The sensor input is in the low-voltage section, separated from the 400 V compressor wiring |
| Cable | `2×2×0,8 mm²` — **two pairs, only one needed**, so a spare pair already runs to the sensor position |
| Characteristic | One of the two tables printed in the manual: PT 1000 or KTY |
| Failure mode | An open circuit raises **`FÜHLERBRUCH E 71`** on the display and in the fault list |

The important consequence: the AFS 2 is a **separate climate sensor on the
house wall**, not a probe inside a refrigerant circuit. Precondition 1 in
section 2 — never manipulate a sensor the unit uses for defrost or compressor
protection — is therefore satisfied. This approach is safe for this pump.

The manual's characteristic table, now encoded as a test in
`tests/test_sensors.py` (`TECALOR_TABLE`):

| °C | PT 1000 Ω | KTY Ω |
|---|---|---|
| −30 | 882 | 1250 |
| −20 | 922 | 1367 |
| −10 | 961 | 1495 |
| 0 | 1000 | 1630 |
| 10 | 1039 | 1772 |
| 20 | 1078 | 1922 |
| 25 | 1097 | 2000 |
| 40 | 1155 | 2245 |
| 100 | 1385 | 3392 |

`Pt1000Sensor` reproduces the PT 1000 column to within 1 Ω and the new
`KtySensor` the KTY column to within 4 Ω, both asserted by tests.

### 7.2 Step 1 — identify the sensor (now optional)

Since §3.6, the box identifies its own sensor once connected, so this
measurement is no longer a gate on ordering parts — build with the switchable
bias and let the calibration decide. It is still the fastest way to know before
you power anything up, and the excitation check in step 5 is not optional.

If you do measure, one reading settles it, because the two candidate
characteristics are hundreds of ohms apart at any plausible outdoor
temperature:

| Outdoor | PT 1000 | KTY |
|---|---|---|
| 5 °C | 1020 Ω | 1700 Ω |
| 10 °C | 1039 Ω | 1772 Ω |
| 15 °C | 1058 Ω | 1846 Ω |
| 20 °C | 1078 Ω | 1922 Ω |

Procedure — **switch the unit off at the isolator first**; the sensor terminals
are SELV but the enclosure they sit in is not, and opening it is installer
territory:

1. Note the outdoor temperature the pump currently shows (`ANLAGE →
   AUSSENTEMPERATUR`, or input register 506 over Modbus — read-only, no writes).
2. Power down. Disconnect the AFS 2 at **X2 `T(A)`** / **X26**.
3. Measure its resistance. ~1 kΩ ⇒ **PT 1000**; ~1.7–1.9 kΩ ⇒ **KTY**. Compare
   against the table for the temperature from step 1 to confirm.
4. Reconnect the sensor, restore power, check the displayed outdoor temperature
   still matches and no `E 71` is logged.
5. While the covers are off, measure the voltage on the X2 `+` terminal
   against `⊥`. Not to power from it (§3.5 explains why not) but because it is
   free information for any future low-power variant.
6. Separately, with the sensor disconnected and the unit powered, measure the
   open-circuit voltage across `T(A)`–X26, then the voltage across a known
   resistor (1 kΩ 0.1 %) in its place, to get the excitation current. This
   decides nothing about the ladder, which has no voltage limit, but it is
   needed if a digital potentiometer is ever used instead.

Record the results in section 6, question 2.

### 7.3 Step 2 — build once, for both

Fit the switchable bias from §3.6 (39 Ω always, 91 Ω shorted by `K2`) and the
AD5272-100. That board works for either sensor, so nothing about the order
depends on step 1.

After it is wired and before `curve run` is trusted with anything, take
calibration observations: at least three, spread over a few days of different
weather and different taps, each a bypass reading of register 506 followed by
an emulated one. Feed them to `identify_sensor()`. It returns the sensor, the
fitted bias and full scale, and a confidence ratio; set `K2` from the answer
and store the fitted emulator as the model the controller plans against.

Re-run it after any change to the board.

### 7.4 Step 3 — bench before house

Never connect a first build to the pump. With the ladder built and the ESP32
driving it:

1. Verify every one of the 512 (or 1024) codes against a four-wire meter.
   `ResistorLadder.resistance_at()` is the expected value; tolerance stack-up
   on 0.1 % parts should stay inside ±1 Ω.
2. Drive the ladder from a spare PT 1000 simulator or a second WPM if one can
   be borrowed, and confirm the displayed temperature tracks.
3. Prove the fail-safe by pulling power mid-sequence: the bypass relay must
   drop and the real sensor must appear at the terminals, with no `E 71`.
4. Let the watchdog time out deliberately and confirm the same.

### 7.5 Step 4 — install

Mount the box at the **indoor unit**, not outdoors, and use the spare pair in
the existing `2×2×0,8 mm²` cable to bring the real AFS 2 into the box. The
emulated pair then runs the short distance to X2/X26. Nothing new needs
pulling through the wall.

Start with `max_shift` at 2 K for a week and the plan applied by hand before
letting `curve run` drive it.

### 7.6 What is still open

- Which characteristic the AFS 2 is (step 1). Everything else is ready for
  both answers.
- The excitation figures, needed only if a digital potentiometer replaces the
  ladder.
- Whether the WPM averages outdoor temperature over 24 h for its heating-season
  decision (section 2, item 6). If it does, long shifts in the shoulder seasons
  need a guard.
