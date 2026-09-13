# The control system that is already running

Before this project writes anything to the heat pump, note that a working
price-aware controller **is already in production** for this house, built from
Home Assistant plus three Node-RED flows, and it drives the same SG Ready
contacts this bridge would target. It is described here so that the bridge
complements it instead of fighting it.

Reconstructed from `nodered-flows-backup-2026-08-23.json` and the Home
Assistant configuration backup. The `packages/` directory
(`configuration.yaml`: `packages: !include_dir_named packages`) was not in the
backup, so the mapping from the three HA helper switches to the two physical
relay outputs is inferred, not read.

## Actuator: relays, not registers

A **Shelly Plus Uni** (`shellyplusuni_a0a3b3688db8`) drives the two SG Ready
contacts. Nothing in this path writes a Modbus register, so the write-endurance
constraint in `virtual-outdoor-sensor.md` §6.1 does not apply to it at all.
This is the same reasoning that makes the sensor emulator attractive: put the
actuator outside the controller's non-volatile memory.

The template sensor `sensor.SG_READY_State` reads the two relay states back and
names the result, which is how the flows know the current state:

| `switch_0` | `switch_1` | Name | SG Ready state |
|---|---|---|---|
| off | off | `Normal` | 2 — normal programmed operation |
| off | on | `Blocked` | 1 — forced down |
| on | off | `Comfort` | 3 — boost |
| on | on | `Ordered` | 4 — immediate maximum |

Note the relay order: `switch_1` is the *blocking* contact (SG Ready "A"),
`switch_0` is the boost contact ("B") — the opposite of the `a`/`b` naming in
this repo's `sgready` backend. Getting this backwards turns a block into a
boost.

Writes go through three HA helper switches — `switch.blocking_mode_switch`
(state 1), `switch.heater_mode_switch` (state 3), `switch.forced_mode_switch`
(state 4) — with "turn all three off" meaning state 2.

## Flow 1 — price analysis, hourly at :03

Computes P20/P40/P80/P90, min and max price, and picks the cheapest morning and
evening DHW windows. Stores them in HA helpers
(`input_number.current_price_percentile`, `input_number.price_p20` …,
`input_datetime.morning_dhw_start`, `input_datetime.evening_dhw_start`). Every
later decision reads these; nothing recalculates prices.

## Flow 2 — DHW control, every 5 minutes

A priority ladder, gated by `input_boolean.dhw_auto_mode`:

| Priority | Condition | Target |
|---|---|---|
| 10 | hour is 05 or 16 **and** DHW < 46 °C | `Ordered` (4) |
| 5 | inside a scheduled 2.5 h window from Flow 1 | `Comfort` (3) |
| 3 | DHW < 30 °C at any time | `Comfort` (3) |
| — | otherwise | no change; space heating keeps control |

While any of these is active it sets `input_boolean.dhw_priority_lock`, which
is how DHW takes the SG Ready contacts away from space heating.

**It only acts on a transition.** The decision function compares the desired
state against the state read back from `sensor.SG_READY_State` and, if they
match, logs *"already set, no SG change needed"* and does nothing. That is the
same write-on-change discipline now enforced in `backends/modbus.py`, arrived
at independently.

## Flow 3 — space heating

Reads Flow 1's percentile (it does no calculations of its own), plus room
temperature and a 4–6 hour lookahead for an upcoming expensive period:

- below P20 → `Comfort`
- below P40 **and** an expensive period is coming → `Comfort` (pre-heat)
- above P90 → `Blocked`, but only while the room is above 19.5 °C
- above P80 → `Blocked`, but only while the room is above 20.0 °C
- floor: never below 19.0 °C

Before writing, `Respect DHW & Debounce` refuses if `dhw_priority_lock` is on,
and debounces an identical state repeated within 10 minutes.

## What this means for this bridge

1. **Do not run the `sgready` or `modbus` backend against this house while the
   flows are live.** Two controllers would drive the same two contacts with no
   shared arbitration; the bridge knows nothing about `dhw_priority_lock`.
2. **Flow 1 + Flow 3 already cover `tibber.py` + `schedule.py`.** Percentile
   classification, pre-heat lookahead, a room-temperature guard and a debounce
   all exist and run today. Re-implementing them adds risk, not function.
3. **The genuinely new part of this repo is `curve.py` and `learning.py`** —
   a fitted house model and a dynamic-programming planner that shifts heat in
   time against a comfort band. Node-RED has no equivalent; its logic is a
   threshold ladder with no model of the building.

So the useful next step is not "switch the house over to the bridge". It is to
run `curve-plan` alongside the existing system, compare its proposed shift with
what Flow 3 actually did, and only then decide whether the curve planner earns
a place — either as a replacement for Flow 3's ladder or as a shift applied
through the emulator, leaving DHW to Flow 2 either way.
