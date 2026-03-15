#!/bin/bash
# init_state.sh — Persist agent state across Railway redeploys
# Symlinks /app/agents/*/state/ → /app/data/agent_state/<agent>/
# The volume at /app/data survives redeploys; agent dirs don't.

STATE_VOL="/app/data/agent_state"
mkdir -p "$STATE_VOL"

for agent_dir in /app/agents/*/state; do
    [ -d "$agent_dir" ] || continue
    # Skip if already a symlink (re-run safety)
    [ -L "$agent_dir" ] && continue

    agent_name=$(basename "$(dirname "$agent_dir")")
    vol_state="$STATE_VOL/$agent_name"
    mkdir -p "$vol_state"

    # Copy git files to volume (don't overwrite existing persisted state)
    cp -n "$agent_dir"/* "$vol_state/" 2>/dev/null || true

    # Replace ephemeral dir with symlink to persistent volume
    rm -rf "$agent_dir"
    ln -s "$vol_state" "$agent_dir"

    echo "[init_state] $agent_name → $vol_state"
done

echo "[init_state] All agent state directories linked to persistent volume"
