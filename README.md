# tibber-heatpump-bridge

Drive **any** heat pump from **Tibber** spot prices, locally, without a
manufacturer cloud in between. The bridge fetches the price curve from the
Tibber API, plans a demand mode for every 15-minute slot and pushes that mode
to the heat pump through **SG Ready contacts**, **Modbus TCP**, **MQTT** or
plain **HTTP** calls. It does locally what Tibber's "smart heating" does for a
NIBE S-series through the myUplink cloud: heat and make hot water when
electricity is cheap, hold back when it is expensive.

## Why not make the heat pump look like a NIBE?

That was the original idea, and it does not work, for a simple reason: Tibber
never talks to a NIBE heat pump directly. Its support article on the NIBE
S-series connection says *"We communicate with the heat pump by sending
commands via Nibe's API"* and asks for your **myUplink login**. Tibber is an
OAuth client of NIBE's **myUplink cloud**; the heat pump itself is only ever
connected to NIBE's servers with NIBE firmware and NIBE device credentials.

So there is no local protocol to emulate. Passing a foreign heat pump off as a
NIBE would mean registering a fake device with NIBE's cloud, which needs their
proprietary device-side protocol and credentials and is against that service's
terms. This project deliberately does not attempt it.

What does work:

1. **Your brand is already supported by Tibber.** Tibber's power-ups cover
   NIBE (S-series via myUplink, F-series via NIBE Uplink), CTC, IVT, Bosch,
   Daikin Altherma, Panasonic Aquarea, Stiebel Eltron, Mitsubishi (MELCloud),
   Ngenic and Sensibo among others. Connect it in the Tibber app and you are
   done.
2. **Anything else:** run this bridge. Practically every modern heat pump has
   an SG Ready input or a Modbus interface, and the Tibber API gives you the
   same prices Tibber's own optimisation uses.

## What it does

```
Tibber API ──prices──▶ scheduler ──mode per slot──▶ backend ──▶ heat pump
                          │                          (SG Ready / Modbus / MQTT / HTTP)
             comfort windows, block limits,
             outdoor-temperature guard, fail-safe
```

Modes, from least to most heat production:

| Mode     | Meaning                                   | SG Ready state |
|----------|-------------------------------------------|----------------|
| `block`  | pause the compressor (utility lock)       | 1              |
| `reduce` | lower heating curve / hot water target    | 2 (or 1)       |
| `normal` | leave the heat pump alone                 | 2              |
| `boost`  | raise heating curve / hot water target    | 3              |
| `force`  | maximum demand, e.g. at negative prices   | 4              |

The heat pump's own controller keeps regulating; the bridge only shifts
*when* it is allowed or encouraged to run.

## Requirements

- Python 3.11 or newer. The core has no third-party dependencies.
- A Tibber account and a personal access token from
  <https://developer.tibber.com/settings/access-token>.
- A way to reach the heat pump: two relays on its SG Ready input (Shelly,
  Tasmota, a Raspberry Pi relay board), Modbus TCP, an MQTT broker, or an
  HTTP endpoint.

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install .              # SG Ready via HTTP relays, HTTP backend, dry run
pip install '.[modbus]'    # adds pymodbus
pip install '.[mqtt]'      # adds paho-mqtt
pip install '.[gpio]'      # adds gpiozero for Raspberry Pi relay boards
```

## Quick start

```bash
cp config.example.toml config.toml      # git-ignored, holds your token
$EDITOR config.toml                     # token, backend, comfort windows

tibber-heatpump-bridge check            # token, home, backend reachable?
tibber-heatpump-bridge plan             # today's and tomorrow's mode plan
tibber-heatpump-bridge plan --slots     # every 15-minute slot with its reason
tibber-heatpump-bridge once --dry-run   # what would be applied right now
tibber-heatpump-bridge run              # keep running (see deploy/ for systemd)
```

`plan` output looks like this (`*` marks the current slot):

```
  Sat 00:00 - Sat 01:45  boost     1h45  avg 0.3246 NOK
  Sat 01:45 - Sat 05:45  normal    4h00  avg 0.6778 NOK
  Sat 07:00 - Sat 09:00  block     2h00  avg 1.7731 NOK
  Sat 09:00 - Sat 12:45  reduce    3h45  avg 1.0307 NOK
* Sat 20:00 - Sun 01:45  boost     5h45  avg 0.1927 NOK

summary: block 4h00 (avg 1.7731) | reduce 11h00 (avg 1.0136) | normal 21h00 (avg 0.7216) | boost 12h00 (avg 0.2004)
now 2026-09-12 22:37: boost (price rank 11/96 on 2026-09-12)
```

Exit codes: `0` ok, `2` configuration error, `3` Tibber API error, `4` backend error.

## Configuration

All settings live in one TOML file; `config.example.toml` documents every key.

### `[tibber]`

| Key          | Default          | Notes                                              |
|--------------|------------------|----------------------------------------------------|
| `token`      |                  | or set the `TIBBER_TOKEN` environment variable     |
| `home_id`    | first home       | needed only for accounts with several homes        |
| `resolution` | `QUARTER_HOURLY` | `HOURLY` for markets still on hourly prices        |

### `[schedule]`

Two strategies:

- **`percentile`** (default) ranks every slot of a local calendar day by
  price. The cheapest `force_share` become `force`, the next `boost_share`
  become `boost`; the most expensive `block_share` become `block`, the next
  `reduce_share` become `reduce`. Everything else is `normal`.
- **`tibber_level`** maps Tibber's own price level (relative to a three-day
  average) to a mode via `[schedule.level_modes]`.

Absolute overrides: `force_below_price` (default `0.0`, so free or negative
prices always force) and `block_only_above_price`.

Comfort limits are applied afterwards and only ever move a slot towards more
comfort:

| Key                           | Default           | Effect                                            |
|-------------------------------|-------------------|---------------------------------------------------|
| `comfort_windows`             | `[]`              | local-time windows where block/reduce become normal |
| `max_block_minutes`           | `120`             | longest consecutive block run (SG Ready allows 2 h) |
| `min_gap_after_block_minutes` | `60`              | recovery time after a block run                   |
| `max_block_minutes_per_day`   | `360`             | daily block budget; cheapest blocks are dropped first |
| `never_block_below_outdoor_c` | unset             | disable blocking in cold weather                  |
| `timezone`                    | home's time zone  | override if needed                                |

### `[outdoor_temperature]` (optional)

Any HTTP endpoint returning JSON plus a dotted `json_path`, e.g. a Home
Assistant entity (`/api/states/sensor.outdoor`, path `state`) or a Shelly H&T
(`/status`, path `tmp.tC`). If the fetch fails the guard is simply skipped.

### `[run]`

| Key                | Default | Effect                                                     |
|--------------------|---------|------------------------------------------------------------|
| `interval_seconds` | `60`    | poll interval; the loop also wakes at every slot boundary  |
| `reapply_minutes`  | `15`    | re-send the current mode even if unchanged (relay reboots) |
| `refresh_minutes`  | `30`    | how often prices are re-fetched                            |
| `retry_minutes`    | `10`    | retry interval after a failed fetch or while tomorrow is missing |
| `stale_plan_hours` | `6`     | without fresh prices for this long, fall back to `normal`  |
| `release_on_exit`  | `true`  | set `normal` when the service stops                        |

**Fail-safe behaviour:** whenever there is no trustworthy plan (Tibber
unreachable for too long, no slot covering the current time, a crash on
shutdown) the bridge applies `normal`, so the heat pump is never left blocked
by accident.

## Backends

### SG Ready (`type = "sgready"`)

Most heat pumps sold in Europe since about 2013 have an SG Ready input: two
potential-free contacts, usually on the installer terminal block, that must be
enabled in the installer menu. Wire each contact to a relay and tell the
bridge how to switch the relays:

```toml
[backend]
type = "sgready"

[backend.sgready.a]
type = "http"
on  = "http://192.168.1.60/rpc/Switch.Set?id=0&on=true"    # Shelly Gen2
off = "http://192.168.1.60/rpc/Switch.Set?id=0&on=false"

[backend.sgready.b]
type = "gpio"          # Raspberry Pi relay board, needs the gpio extra
pin = 17
```

| SG Ready state | A | B | Meaning                     | default for mode     |
|----------------|---|---|-----------------------------|----------------------|
| 1              | 1 | 0 | blocked (max 2 h at a time) | `block`              |
| 2              | 0 | 0 | normal                      | `reduce`, `normal`   |
| 3              | 0 | 1 | recommended on              | `boost`              |
| 4              | 1 | 1 | forced on                   | `force`              |

Change the mapping with `modes = { reduce = 1, ... }` if you prefer a hard
block for `reduce`. What state 3 and 4 do (how far set points are raised) is
configured in the heat pump's installer menu.

### HTTP (`type = "http"`)

One or more requests per mode; covers Shelly and Tasmota relays, Home
Assistant webhooks and anything with a REST API. See `config.example.toml`.

### Modbus TCP (`type = "modbus"`)

A list of holding-register or coil writes per mode. Addresses and values come
from your heat pump's Modbus manual; nothing in the bridge is device specific.
Negative values are written as 16-bit two's complement, which is how signed
registers such as a heating-curve offset are usually encoded.

**Write endurance.** A register that holds a *parameter* — a setpoint, a curve
rise — lives in the controller's non-volatile memory and survives a finite
number of write cycles. Re-sending the same value every `reapply_minutes`
would spend roughly 35 000 of them a year, per register, for no effect. The
backend therefore writes such a register **only when the value changes**, and
`max_writes_per_day` adds a hard per-address budget; when it is spent the
write is refused and logged and the heat pump keeps its current setting.

Mark targets that do *not* persist with `volatile = true` — coils, and
registers that merely emulate a contact such as Stiebel/Tecalor's SG Ready
inputs. Those are rewritten every tick, so a device that rebooted is repaired.
See `docs/virtual-outdoor-sensor.md` §6.1.

### MQTT (`type = "mqtt"`)

Publishes the mode name (or a per-mode payload) to one topic with `retain`,
for setups where Home Assistant, Node-RED or an ESPHome board does the last
hop.

## Heating-curve shifting (virtual outdoor sensor)

Ngenic Tune makes any heat pump price-aware by feeding it a manipulated
outdoor temperature; the pump's own heating curve then heats more or less.
`docs/virtual-outdoor-sensor.md` designs the same thing for this project:
the hardware that replaces the sensor signal (a digital potentiometer or a
relay ladder behind a fail-safe bypass relay, with an ESPHome sketch in
`firmware/`), and the control logic that is already implemented here:

- `curve.py` — a small house model (`dT/dt = c − a·T + b·shift + d·T_out`)
  and a dynamic-programming planner that picks a shift per price slot so the
  room stays inside a comfort band while heating moves into cheap slots.
- `learning.py` — fits the model from a CSV log (`curve-fit`), with a
  recursive least-squares variant for learning while running.
- `sensors.py` — NTC and PT1000 resistance maths and digital potentiometer
  tap calculation.

```bash
tibber-heatpump-bridge curve-plan --indoor 21.3 --outdoor 2.0     # plan against live prices
tibber-heatpump-bridge curve-fit heating-log.csv                 # learn the house model
```

`curve-plan` prints the planned shift runs with the predicted indoor
temperature, the cost against not shifting, and the outdoor temperature (and
potentiometer tap) to present right now. The runtime loop that applies the
plan through the emulator is the next step and is described in the design
document.

## Running as a service

`deploy/tibber-heatpump-bridge.service` is a systemd unit with setup notes.
For a cron-style setup instead of a daemon, run `tibber-heatpump-bridge once`
every 15 minutes; it applies the mode for the current slot and exits.

## Development

```bash
pip install -e '.[dev]'
python -m pytest        # unit tests, no network
ruff check . && ruff format --check .
```

Set `TIBBER_API_URL` to point the client at a local mock server; `tools/fake_tibber.py` is one (token `smoke-token`).

## Status and where to continue

Development happens on `main` in
<https://github.com/auster80/ESP32_Heatpump>. The project started in the
`Claude_Code_Default` scratch repository and was moved here with its history.

- `docs/existing-home-assistant-control.md` — **read this first.** A working
  price-aware controller is already in production for the target house (Home
  Assistant + three Node-RED flows driving the SG Ready contacts through a
  Shelly Plus Uni). It already covers what `tibber.py` and `schedule.py` do,
  and the bridge must not drive the same contacts alongside it.
- `docs/tibber-integrations.md` — which Tibber integrations could carry a
  bridge (Homey, Futurehome, Ngenic) and which cannot (vendor clouds).
- `docs/virtual-outdoor-sensor.md` — design of the Ngenic-style sensor
  emulator and its control logic. Section 6 records the target installation (a
  Tecalor TTF 13 cool behind an ISG plus gateway, −19 °C design floor, The
  Hague), why write endurance rules out continuously writing setpoint
  registers, and why the emulator is still the better long-term design even
  though this pump does have Modbus.
- Not built yet: the runtime loop that applies `curve-plan` to the heat pump
  (`curve run`), the emulator hardware, and any Homey or Futurehome adapter.
- The part of this repo with no counterpart in the existing system is the
  modelled curve shifting (`curve.py`, `learning.py`). The next step is to run
  `curve-plan` in parallel with the Node-RED flows and compare, not to switch
  the house over.

## Limitations

- The bridge only shifts demand in time. Tibber's own NIBE integration also
  uses a room sensor and a weather forecast; here the heat pump's controller
  keeps doing the actual temperature regulation.
- Tomorrow's prices are published around 13:00 local time; until then the plan
  covers only today.
- Not affiliated with Tibber or NIBE.

## References

- Tibber support, [MyUplink for Nibe S-series](https://support.tibber.com/sv/articles/6065031-myuplink-for-nibe-s-serie)
- Tibber support, [Brands and Power-ups](https://support.tibber.com/en/collections/3402088-brands-and-power-ups)
- Tibber developer, [API reference](https://developer.tibber.com/docs/reference)
- NIBE, [How do I connect my S-series heat pump to myUplink?](https://www.nibe.eu/en-eu/products/smart-home-accessories/faq-smart-home-accessories/how-do-i-connect-my-s-series-heat-pump-to-myuplink)
