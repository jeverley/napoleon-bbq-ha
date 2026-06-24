#!/usr/bin/env bash
#
# .devcontainer/hooks/on-create.post.sh - Personal on-create hook
#
# Runs after the main on-create setup (volume ownership fix). This file is
# protected from template sync (.devcontainer/hooks/ is in .templatesyncignore).
#

set -e

# Fix ownership of Claude Code data volume.
# Docker initialises named volume mount points as root:root; Claude Code needs
# to write here as vscode before any lifecycle hook runs.
sudo chown vscode:vscode /home/vscode/.claude

# One-time migration: copy data from the old symlink-based persistence location
# (.ai-scratch/.claude/) to the new named volume, but only when the volume is
# empty (i.e. first rebuild after switching approaches).
CLAUDE_SCRATCH="${CONTAINER_WORKSPACE_FOLDER:-/workspaces/$(basename "$(git rev-parse --show-toplevel)")}/.ai-scratch/.claude"
if [[ -d "$CLAUDE_SCRATCH" ]] && [[ -z "$(ls -A "$HOME/.claude" 2>/dev/null)" ]]; then
    echo "Migrating Claude Code data from .ai-scratch/.claude/ to named volume..."
    cp -a "$CLAUDE_SCRATCH/." "$HOME/.claude/"
fi
