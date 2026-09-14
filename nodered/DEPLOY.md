# Deploying

Node-RED sits behind Home Assistant's ingress auth (`192.168.0.137:1880` returns
401 to the admin API), so this is a manual paste through the editor. That is the
right way round for a first deploy anyway — it is the heating system, and the
editor shows you what changed.

**Nothing needs rewiring.** Both downstream switch nodes already match the output
shape: `Route by Target State` reads `payload.targetState`
(Blocked/Normal/Comfort/Ordered) and `DHW Lock ON/OFF Router` reads
`payload.action` (on/off). The decision node keeps its two outputs.

## 0. Back up first

Node-RED menu → **Export** → **All flows** → Download. Keep the file; it is the
rollback.

## 1. Check the mixing valve

The evening fill uses **Ordered = 60 °C**. Confirm the tap mixing valve is set
for that before deploying node 02. This is the one step with a scald risk.

## 2. Deploy the planner (`01-plan-dhw-windows.js`)

Tab **Flow 1: Price Analysis + Hourly Percentile**. There are **two** copies of
*Calculate Windows + Percentiles* — the 06:00 run and the 13:30 run:

| id | |
|---|---|
| `ca05805e1de0e620` | one copy |
| `9cd020f6aea6d5bc` | the other |

Paste the same new code into **both**. The new node plans the morning *and*
evening window on every invocation, so the old `runType` morning/afternoon split
no longer matters — that is why both copies get identical code.

Deploy (Modified Nodes is enough).

## 3. Watch for a day before going further

The planner only writes `flow.dhwPlan`; nothing acts on it until step 4, so this
is safe to observe. In the debug pane you should see lines like:

```
[DHW] evening window: 14/09/2026, 11:00:00 → 13:30:00 @ 0.1840
[DHW] morning window: 15/09/2026, 02:00:00 → 04:30:00 @ 0.2290
```

Sanity check: the chosen windows should sit in the cheap hours for the season —
**overnight (01–04) in deep winter, midday (10–13) from March onward**. If they
do not, stop and investigate before step 4.

## 4. Deploy the decision node (`02-dhw-decision.js`)

Tab **Flow 2: DHW Control (Fixed)**, node *DHW Decision Logic (FIXED)*, id
`58e0b70379e36b7e`. Paste and deploy.

Check the inputs are present on `msg` from the preceding `api-current-state`
nodes — the node needs `msg.dhw_temp`, `msg.current_state` and `msg.auto_mode`.
If your existing nodes populate different property names, adjust the three
`msg.` reads at the top rather than rewiring.

## 5. Watch for a week

| Watch | Expect |
|---|---|
| Tank temperature | Should not sit below 40 °C more than it did before |
| Anyone running out of hot water | Should not happen |
| Debug log | Raises land in cheap hours; blocks in expensive ones |

If hot water ever runs short, raise `PRICE_FLOOR_TEMP` from 43 toward 46. That
releases the price gate earlier and trades a little saving for more margin. It
is the first knob to turn, not the window length.

## Rollback

Import the backup from step 0, or paste the original function bodies back. There
is no persistent state to unwind — the only thing the new code writes is
`flow.dhwPlan`, which the old code overwrites on its next run.

## What to expect

Honestly: **nothing between November and February.** The winter price spread is
too narrow for any scheduler. The gain shows up from March at roughly
€12–14/month. If you deploy now (September) you should see it immediately, then
watch it fade through the winter and return in spring.
