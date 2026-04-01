# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This repository contains a shell-based utility for checking whether the installed version of Claude Code is up to date compared to the latest published version on npm.

## Running the Script

```bash
./check-updates.sh
```

Exit codes: `0` = update available, `1` = up to date, `2` = error.

## Dependencies

- `claude` CLI must be installed (used to get the installed version)
- Either `npm` or `curl` (used to fetch the latest version from the npm registry)

## Architecture

`check-updates.sh` is a single self-contained Bash script with three functions:

- `get_installed_version` — parses `claude --version` output
- `get_latest_version` — queries npm registry (prefers `npm view`, falls back to `curl`)
- `main` — compares versions and reports result
