#!/bin/bash
#
# .devcontainer/hooks/on-create.post.sh - Personal on-create hook
#
# Runs after the main on-create setup (volume ownership fix). This file is
# protected from template sync (.devcontainer/hooks/ is in .templatesyncignore).
#

set -euo pipefail

WORKSPACE_ROOT="${CONTAINER_WORKSPACE_FOLDER:-$(git rev-parse --show-toplevel)}"
CLAUDE_SCRATCH="$WORKSPACE_ROOT/.ai-scratch/.claude"

mkdir -p "$CLAUDE_SCRATCH"

mkdir -p "$HOME/.claude"
sudo chown vscode:vscode "$HOME/.claude"

if [[ -z "$(find "$HOME/.claude" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]] && [[ -d "$CLAUDE_SCRATCH" ]]; then
    if [[ -n "$(find "$CLAUDE_SCRATCH" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
        echo "Migrating Claude Code data from .ai-scratch/.claude/ to the Claude volume..."
        cp -a "$CLAUDE_SCRATCH/." "$HOME/.claude/"
    fi
fi
