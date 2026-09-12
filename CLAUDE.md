# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This repository holds two independent pieces:

1. `check-updates.sh`, a shell utility that checks whether the installed Claude Code is up to date against npm.
2. `tibber_heatpump_bridge/`, a Python package that drives a heat pump from Tibber spot prices (see README.md).

## check-updates.sh

```bash
./check-updates.sh
```

Exit codes: `0` = update available, `1` = up to date, `2` = error.

Dependencies: the `claude` CLI (installed version) and either `npm` or `curl` (latest version from the npm registry).

Single self-contained Bash script with three functions: `get_installed_version` parses `claude --version`, `get_latest_version` queries the npm registry (prefers `npm view`, falls back to `curl`), `main` compares and reports.

## tibber-heatpump-bridge

Python 3.11+, standard library only in the core; `pymodbus`, `paho-mqtt` and `gpiozero` are optional extras imported lazily inside their backends.

```bash
pip install -e '.[dev]'
python -m pytest                       # unit tests, no network access needed
ruff check . && ruff format --check .  # lint and formatting (line length 110)
python -m tibber_heatpump_bridge -c config.toml plan   # CLI without installing the script
```

Architecture (data flows left to right):

- `tibber.py` — GraphQL client for `priceInfo(resolution: QUARTER_HOURLY|HOURLY)`; turns `today` + `tomorrow` into contiguous `PriceSlot`s. `TIBBER_API_URL` overrides the endpoint for mocks.
- `schedule.py` — `Mode` enum (block/reduce/normal/boost/force), `build_plan()` classifies slots per local day (percentile or Tibber level) and then applies constraints that only ever move a slot towards more comfort (comfort windows, outdoor guard, max block run + recovery gap, daily block budget).
- `backends/` — `Backend.apply(mode)` implementations: `dryrun`, `http`, `sgready` (two relay channels, HTTP or GPIO), `modbus`, `mqtt`. `build_backend(type, options)` constructs one from the `[backend]` config table and validates the options.
- `config.py` — TOML loading into dataclasses with `ConfigError` messages that name the offending key.
- `controller.py` — refresh/decide/apply loop with fail-safe: no plan, stale plan or uncovered time means `normal`. Backend errors propagate so the mode is retried on the next tick.
- `cli.py` — `plan`, `once`, `run`, `check` subcommands; exit codes 0/2/3/4 (ok/config/tibber/backend).

Conventions:

- Keep the core free of third-party dependencies; new optional integrations go into `backends/` behind a lazy import and an extra in `pyproject.toml`.
- Constraints in `schedule.py` must never make a slot less comfortable than the classification did (downgrade direction only).
- Tests use fakes injected via `transport=`, `sender=` and `client_factory=`; never hit the network in tests.
- `config.toml` is git-ignored because it contains the Tibber token; edit `config.example.toml` when adding options and keep it loadable (a test loads it).
