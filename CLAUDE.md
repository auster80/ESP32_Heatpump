# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`tibber_heatpump_bridge/` is a Python package that drives a heat pump from
Tibber spot prices (see README.md), plus an ESPHome sketch under `firmware/`
for the planned virtual-outdoor-sensor hardware.

## tibber-heatpump-bridge

Python 3.11+, standard library only in the core; `pymodbus`, `paho-mqtt` and `gpiozero` are optional extras imported lazily inside their backends.

```bash
pip install -e '.[dev]'
python -m pytest                       # unit tests, no network access needed
ruff check . && ruff format --check .  # lint and formatting (line length 110)
python -m tibber_heatpump_bridge -c config.toml plan   # CLI without installing the script
python tools/fake_tibber.py &   # local fake Tibber API for smoke tests (TIBBER_API_URL=http://127.0.0.1:8765/gql, token smoke-token)
```

Architecture (data flows left to right):

- `tibber.py` — GraphQL client for `priceInfo(resolution: QUARTER_HOURLY|HOURLY)`; turns `today` + `tomorrow` into contiguous `PriceSlot`s. `TIBBER_API_URL` overrides the endpoint for mocks.
- `schedule.py` — `Mode` enum (block/reduce/normal/boost/force), `build_plan()` classifies slots per local day (percentile or Tibber level) and then applies constraints that only ever move a slot towards more comfort (comfort windows, outdoor guard, max block run + recovery gap, daily block budget).
- `backends/` — `Backend.apply(mode)` implementations: `dryrun`, `http`, `sgready` (two relay channels, HTTP or GPIO), `modbus`, `mqtt`. `build_backend(type, options)` constructs one from the `[backend]` config table and validates the options.
- `config.py` — TOML loading into dataclasses with `ConfigError` messages that name the offending key.
- `controller.py` — refresh/decide/apply loop with fail-safe: no plan, stale plan or uncovered time means `normal`. Backend errors propagate so the mode is retried on the next tick.
- `cli.py` — `plan`, `once`, `run`, `check`, `curve-plan`, `curve-fit` subcommands; exit codes 0/2/3/4 (ok/config/tibber/backend).

Curve shifting (virtual outdoor sensor, see `docs/virtual-outdoor-sensor.md`):

- `curve.py` — `HouseModel` (`dT/dt = c − a·T + b·shift_eff + d·T_out`, first-order lag `filter_minutes` on the shift), `PowerModel`, `CurveSettings`, and `plan_curve()`: a dynamic programme over (indoor temperature, effective shift) minimising price cost + comfort penalty + band-violation penalty, with a terminal term valuing stored heat at the mean price. `merge_slots()` coarsens price slots for speed.
- `learning.py` — batch least squares and `RecursiveLeastSquares`; `fit_house_model()` / `fit_power_model()` from `Observation` rows; CSV read/write (`time,indoor_c,outdoor_c,shift[,power_kw]`, row k's shift applies until row k+1).
- `sensors.py` — `NtcSensor` (beta model), `Pt1000Sensor` (Callendar-Van Dusen), `DigitalPotentiometer` tap maths, `fake_temperature(real, shift) = real − shift`.
- `firmware/esphome-outdoor-sensor-emulator.yaml` — untested ESPHome sketch for the emulator hardware.
- Sign convention everywhere: positive shift = pretend it is colder = more heat.

Conventions:

- Keep the core free of third-party dependencies; new optional integrations go into `backends/` behind a lazy import and an extra in `pyproject.toml`.
- Constraints in `schedule.py` must never make a slot less comfortable than the classification did (downgrade direction only).
- Tests use fakes injected via `transport=`, `sender=` and `client_factory=`; never hit the network in tests.
- `config.toml` is git-ignored because it contains the Tibber token; edit `config.example.toml` when adding options and keep it loadable (a test loads it).
