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

```
                 ┌──────────────────────────────────────────────────────────┐
                 │  emulator (near the indoor unit)                          │
   real outdoor  │  ┌─────────────┐   ┌──────────┐   ┌─────────────────────┐ │
   sensor ───────┼─►│ ADS1115 +   │──►│  ESP32   │──►│ AD5272 digipot      │─┼──┐
   (2 wires)     │  │ 10k 0.1 %   │   │ ESPHome  │   │ (isolated section)  │ │  │
                 │  │ divider     │   │ MQTT     │   └─────────────────────┘ │  │  DPDT relay
                 │  └─────────────┘   │ watchdog │──► relay coil             │  │  NC: real sensor
                 │                    └──────────┘                           │  │  NO: emulated
                 └───────────────────────────────────────────────────────────┘  ▼
                                                                         heat pump sensor input
```

### Option A: digital potentiometer (NTC sensors, excitation ≤ 5 V)

- **Resistance emulation:** Analog Devices AD5272-100 (100 kΩ, 1024 taps,
  I²C, ±1 % end-to-end, ~35 Ω wiper). In rheostat mode it produces
  35 Ω … 100 kΩ in 98 Ω steps. With a 10 kΩ NTC that is 0.08 K resolution
  at 0 °C and 0.3 K at 25 °C, and it covers **−19 °C to +50 °C**. For colder
  climates put two AD5272-100 in series (−30 °C, 2048 taps) or switch a
  fixed 47 kΩ resistor in series with a small relay below −15 °C.
  `tibber-heatpump-bridge curve-plan` prints the tap for the configured part.
- **Isolation:** the pump's sensor input is referenced to its controller
  ground. Put the AD5272 on an isolated 5 V rail (a B0505S-1W isolated DC/DC)
  behind an I²C isolator (TI ISO1540). The pot terminals then float at
  whatever the pump uses. Skipping isolation works on some pumps and
  destroys the controller on others; do not skip it.
- **Write enable:** the AD5272 powers up with the wiper frozen. Write
  control register bit 1 (`0x1C 0x02`) once after boot before RDAC writes
  (`0x04|hi, lo`). Address 0x2F with ADDR tied to GND.
- **Reading the real sensor:** the sensor is disconnected from the pump and
  measured by us: a ratiometric divider with a 10 kΩ 0.1 % reference against
  3.3 V into an ADS1115 (16-bit, I²C). ESPHome's `resistance` and `ntc`
  components turn that into °C with the same beta the pump uses. An
  alternative is to ignore the original sensor and mount a DS18B20 next to
  it, but reusing the original keeps the pump's calibration.
- **Fail-safe relay:** a DPDT signal relay (e.g. Omron G6K-2P) carries the
  two sensor wires. Its normally-closed contacts connect the real sensor to
  the pump; the coil is driven only while the ESP32 refreshes a hardware
  watchdog (a TPL5010 or a simple 555 retriggerable monostable with a ~15 min
  period fed by a heartbeat pin). Power loss, a firmware hang, or a stalled
  controller all drop the relay and the pump sees its real sensor again.

### Option B: switched resistor ladder (PT1000, or any excitation voltage)

PT1000 spans only 880 Ω (−30 °C) to 1155 Ω (+40 °C), 3.85 Ω/K. No common
digital potentiometer has both a ≤ 1 kΩ range and 1000 taps, so use a fixed
850 Ω 0.1 % resistor plus a binary-weighted ladder: 1, 2, 4, 8, 16, 32, 64,
128, 256 Ω (nine 0.1 % resistors), each shorted by a latching signal relay.
That gives 0–511 Ω in 1 Ω steps (0.26 K), no voltage limit, galvanic
isolation for free, and zero coil power between changes. The same ladder
with 100 Ω … 51.2 kΩ elements emulates a 10 kΩ NTC on pumps with 12 V or
pulsed excitation. Nine relays are more soldering but nothing exotic.

### Option C: active emulation (advanced)

An op-amp current sink that measures the voltage across the terminals and
sinks `V / R_target` emulates any resistance at any excitation with DAC
resolution, but it must be stable against the pump's sampling scheme and is
harder to make fail-safe. Only worth it if A and B do not fit.

### Bill of materials (option A)

| Part                                   | Approx. price | Note                                      |
|----------------------------------------|---------------|-------------------------------------------|
| ESP32 dev board                        | 8 €           | ESPHome, Wi-Fi, MQTT                      |
| ADS1115 module                         | 4 €           | 16-bit ADC for the real sensor            |
| AD5272BRMZ-100 (×1 or ×2)              | 6 € each      | 1024-tap 100 kΩ digipot                   |
| ISO1540 I²C isolator + B0505S DC/DC    | 8 €           | galvanic isolation of the pot section     |
| DPDT signal relay + driver transistor  | 3 €           | fail-safe bypass                          |
| TPL5010 or NE555 watchdog              | 2 €           | hardware heartbeat                        |
| 10 kΩ 0.1 % resistor, passives, box    | 5 €           |                                           |

Under 50 € in parts. A commercial Ngenic Tune plus gateway is a few hundred
euros and needs its cloud; this box needs only MQTT on your LAN.

## 4. Firmware

`firmware/esphome-outdoor-sensor-emulator.yaml` is an ESPHome sketch for
option A: it publishes the real outdoor temperature, subscribes to a target
temperature, writes the AD5272 tap, and drops the bypass relay when no
heartbeat arrives for 20 minutes or the target is out of bounds. It is
written against the datasheet and ESPHome documentation but has not been
run on hardware; treat it as a starting point and verify the I²C frames
with a logic analyser before connecting the pump.

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

### 7.2 Step 1 — the one measurement that unblocks everything

Open question 2 reduces to a single reading, because the two candidate
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
5. Separately, with the sensor disconnected and the unit powered, measure the
   open-circuit voltage across `T(A)`–X26, then the voltage across a known
   resistor (1 kΩ 0.1 %) in its place, to get the excitation current. This
   decides nothing about the ladder, which has no voltage limit, but it is
   needed if a digital potentiometer is ever used instead.

Record the results in section 6, question 2.

### 7.3 Step 2 — the ladder, sized for each outcome

Both branches are already modelled by `ResistorLadder` in `sensors.py`, so the
firmware can be written against either. Figures below are computed, not
estimated — see the tests.

**If PT 1000** (the likely case): base 850 Ω 0.1 % plus binary-weighted
1, 2, 4, 8, 16, 32, 64, 128, 256 Ω, nine 0.1 % resistors, each shorted by a
latching relay.

- Range 850 … 1361 Ω = **−38 °C … +94 °C**, comfortably past the −19 °C floor
- Resolution **0.25 K** across the whole heating range
- −19 °C is tap 76, 0 °C is tap 150, 20 °C is tap 228

**If KTY**: base 1240 Ω plus 2, 4, 8, … 1024 Ω (ten resistors, 2 Ω steps).

- Range 1240 … 3286 Ω = **−31 °C … +95 °C**
- Resolution **0.13–0.16 K**

Everything else in section 3 is unchanged: latching relays so nothing draws
coil current between changes, and the DPDT bypass relay carrying both sensor
wires with the real AFS 2 on the normally-closed contacts.

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
