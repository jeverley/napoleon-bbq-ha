#!/usr/bin/env bash
#
# .devcontainer/hooks/post-create.post.sh - Personal post-create hook
#
# Runs after the main post-create setup. This file is protected from template
# sync (.devcontainer/hooks/ is in .templatesyncignore) so personal tooling
# added here survives upstream template updates.
#

set -e

# Install Claude Code CLI globally
npm install -g @anthropic-ai/claude-code

# Install personal VS Code extensions listed in devcontainer-extensions.json
# (template-managed extensions remain in devcontainer.json)
EXTENSIONS_FILE="${CONTAINER_WORKSPACE_FOLDER:-$(git rev-parse --show-toplevel)}/.devcontainer/devcontainer-extensions.json"
if [[ -f "$EXTENSIONS_FILE" ]] && command -v code &>/dev/null; then
    while IFS= read -r ext; do
        [[ -z "$ext" ]] && continue
        echo "Installing extension: $ext"
        code --install-extension "$ext" --force
    done < <(jq -r '.recommendations[]?' "$EXTENSIONS_FILE")
fi
