#!/usr/bin/env python3
"""Survey the Home Assistant InfluxDB for the heat pump control analysis.

Answers questions 3, 5 and 6 of docs/control-design.md against real data.
Standard library only, so it runs with no install.

The token is never passed on the command line (it would land in shell history
and in the process list). Put a **read-only** token in one of:

    $INFLUX_TOKEN
    ~/.config/influx-heatpump-token

Generate one at http://192.168.0.137:8086 -> Load Data -> API Tokens ->
Generate API Token -> Custom, read access to the bucket, no write.

    python3 scripts/influx_survey.py discover
    python3 scripts/influx_survey.py pull --start 2025-11-01 --end 2026-03-31
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

HOST = os.environ.get("INFLUX_HOST", "http://192.168.0.137:8086")
TOKEN_FILE = pathlib.Path.home() / ".config" / "influx-heatpump-token"


def token() -> str:
    tok = os.environ.get("INFLUX_TOKEN")
    if not tok and TOKEN_FILE.exists():
        tok = TOKEN_FILE.read_text().strip()
    if not tok:
        sys.exit(
            f"No token. Put a read-only token in $INFLUX_TOKEN or {TOKEN_FILE}.\n"
            "See the module docstring for how to generate one."
        )
    return tok


def _request(path: str, *, data: bytes | None = None, headers: dict | None = None) -> str:
    req = urllib.request.Request(f"{HOST}{path}", data=data, method="POST" if data else "GET")
    req.add_header("Authorization", f"Token {token()}")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.read().decode()
    except urllib.error.HTTPError as exc:
        sys.exit(f"{exc.code} {exc.reason}: {exc.read().decode()[:400]}")


def orgs() -> list[dict]:
    return json.loads(_request("/api/v2/orgs")).get("orgs", [])


def buckets() -> list[dict]:
    return json.loads(_request("/api/v2/buckets?limit=100")).get("buckets", [])


def flux(query: str, org: str) -> str:
    return _request(
        "/api/v2/query?" + urllib.parse.urlencode({"org": org}),
        data=query.encode(),
        headers={"Content-Type": "application/vnd.flux", "Accept": "application/csv"},
    )


def cmd_discover(args: argparse.Namespace) -> None:
    found = orgs()
    print("orgs:", ", ".join(o["name"] for o in found) or "(none)")
    print("buckets:")
    for b in buckets():
        print(f"  {b['name']:<28} retention={b.get('retentionRules')}")
    if not found:
        return
    org = args.org or found[0]["name"]
    for b in buckets():
        if b["name"].startswith("_"):
            continue
        print(f"\n--- measurements in {b['name']} ---")
        out = flux(
            f'import "influxdata/influxdb/schema"\nschema.measurements(bucket: "{b["name"]}")',
            org,
        )
        names = [line.split(",")[-1].strip() for line in out.splitlines()[1:] if line.strip()]
        print("  " + ", ".join(sorted(set(names))[:40]))


def cmd_entities(args: argparse.Namespace) -> None:
    org = args.org or orgs()[0]["name"]
    out = flux(
        f'import "influxdata/influxdb/schema"\nschema.tagValues(bucket: "{args.bucket}", tag: "entity_id")',
        org,
    )
    names = sorted({line.split(",")[-1].strip() for line in out.splitlines()[1:] if line.strip()})
    needle = args.match.lower()
    hits = [n for n in names if needle in n.lower()] if needle else names
    print(f"{len(hits)} of {len(names)} entities match {args.match!r}:")
    for n in hits:
        print("  " + n)


def cmd_pull(args: argparse.Namespace) -> None:
    """Export the series the analysis needs, one CSV per entity."""
    org = args.org or orgs()[0]["name"]
    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for entity in args.entity:
        query = (
            f'from(bucket: "{args.bucket}")\n'
            f"  |> range(start: {args.start}T00:00:00Z, stop: {args.end}T00:00:00Z)\n"
            f'  |> filter(fn: (r) => r["entity_id"] == "{entity}")\n'
            f'  |> filter(fn: (r) => r["_field"] == "value" or r["_field"] == "state")\n'
            f"  |> aggregateWindow(every: {args.every}, fn: last, createEmpty: false)\n"
            f'  |> keep(columns: ["_time", "_value"])'
        )
        path = out_dir / f"{entity}.csv"
        path.write_text(flux(query, org))
        print(f"  {entity} -> {path} ({path.stat().st_size} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--org", default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("discover").set_defaults(func=cmd_discover)

    p_ent = sub.add_parser("entities")
    p_ent.add_argument("--bucket", required=True)
    p_ent.add_argument("--match", default="")
    p_ent.set_defaults(func=cmd_entities)

    p_pull = sub.add_parser("pull")
    p_pull.add_argument("--bucket", required=True)
    p_pull.add_argument("--start", required=True, help="YYYY-MM-DD")
    p_pull.add_argument("--end", required=True, help="YYYY-MM-DD")
    p_pull.add_argument("--every", default="5m")
    p_pull.add_argument("--out", default="data")
    p_pull.add_argument("entity", nargs="+")
    p_pull.set_defaults(func=cmd_pull)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
