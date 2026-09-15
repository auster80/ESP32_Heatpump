# Deployment record — 2026-09-15

The two Node-RED nodes were deployed to the live system over SSH.

## What is live

| Node id | Name | Now running |
|---|---|---|
| `ca05805e1de0e620` | Calculate Windows + Percentiles (run A) | `01-plan-dhw-windows.js` |
| `9cd020f6aea6d5bc` | Calculate Windows + Percentiles (run B) | `01-plan-dhw-windows.js` |
| `58e0b70379e36b7e` | DHW Decision Logic (FIXED) | `02-dhw-decision.js` |

Only these three `func` fields changed; all 305 nodes, wiring and IDs are
otherwise byte-identical to the pre-deploy file. Node-RED restarted healthy,
"Started flows" with no errors, and the decision node logged correctly on its
first run (`[DHW] 53.2°C P39 Normal → Normal: no action`).

## Access used

- HA "Advanced SSH & Web Terminal" add-on, **port 22**, login user **martin**
  (uid 1000, wheel), key-based, `sudo` available.
- `PermitRootLogin no`, so the deploy key lives in the global
  **`/etc/ssh/authorized_keys`** and login is as `martin`, not root.
- flows.json: `/addon_configs/a0d7b954_nodered/flows.json`
- Node-RED container: `app_a0d7b954_nodered` (restart with
  `sudo docker restart app_a0d7b954_nodered`; the `ha` CLI lacks a supervisor
  token in this shell).

## First planner run

The planner fires on its schedule (≈06:00 and ≈13:30), so `flow.dhwPlan` is
empty until the first run after the restart. Overnight the decision node still
runs safely (safety, emergency, block and release paths need no plan); the
window-based fills begin at the next scheduled planner run. No action needed.

## Rollback

On the box:

```bash
sudo cp /addon_configs/a0d7b954_nodered/flows.json.bak-20260915-213236 \
        /addon_configs/a0d7b954_nodered/flows.json
sudo docker restart app_a0d7b954_nodered
```

A copy of the pre-deploy flows is also saved off-box in the session scratch as
`flows.live-20260915-213236.json`.

## Revoking Claude's access when you are done

The deploy key was added to `/etc/ssh/authorized_keys`. To remove it:

```bash
sudo sed -i '/claude-heatpump-deploy/d' /etc/ssh/authorized_keys
```

Then re-enable **Protection mode** on the add-on (Info tab) if you want the
sandbox back. Both are optional but recommended once you are satisfied.

## What to watch

- Tomorrow: check the debug pane shows `[DHW] evening window …` / `morning
  window …` lines landing in the day's cheap hours (midday now; overnight in
  deep winter).
- This week: tank should not sit below 40 °C more than before; nobody should
  run short of hot water. If they do, raise `PRICE_FLOOR_TEMP` (43 → 46) in the
  decision node.
- Expect **no measurable saving until March** — the winter spread is too narrow.
