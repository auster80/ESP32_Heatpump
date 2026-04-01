#!/usr/bin/env bash
#
# check-updates.sh — Check if a newer version of Claude Code is available.
#
# Usage:
#   ./check-updates.sh
#
# Exit codes:
#   0 — update available (prints new version)
#   1 — already up to date
#   2 — error (could not determine versions)

set -euo pipefail

PACKAGE_NAME="@anthropic-ai/claude-code"

get_installed_version() {
    if command -v claude &>/dev/null; then
        claude --version 2>/dev/null | head -1 | grep -oP '\d+\.\d+\.\d+' || return 1
    else
        echo "Error: claude is not installed." >&2
        return 1
    fi
}

get_latest_version() {
    if command -v npm &>/dev/null; then
        npm view "$PACKAGE_NAME" version 2>/dev/null || return 1
    elif command -v curl &>/dev/null; then
        curl -s "https://registry.npmjs.org/${PACKAGE_NAME}/latest" 2>/dev/null \
            | grep -oP '"version"\s*:\s*"\K[^"]+' || return 1
    else
        echo "Error: npm or curl is required to check for updates." >&2
        return 1
    fi
}

main() {
    local installed latest

    installed=$(get_installed_version) || exit 2
    latest=$(get_latest_version) || exit 2

    if [ -z "$installed" ] || [ -z "$latest" ]; then
        echo "Error: could not determine versions." >&2
        exit 2
    fi

    echo "Installed: $installed"
    echo "Latest:    $latest"

    if [ "$installed" = "$latest" ]; then
        echo "Claude Code is up to date."
        exit 1
    else
        echo "Update available! Run 'claude update' to upgrade."
        exit 0
    fi
}

main
