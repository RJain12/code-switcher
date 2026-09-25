#!/usr/bin/env sh
# Installs `code` into ~/.local/bin (override with PREFIX=/some/bin).
set -e
PREFIX="${PREFIX:-$HOME/.local/bin}"
REPO_RAW="https://raw.githubusercontent.com/RJain12/code-switcher/main/code"
mkdir -p "$PREFIX"
if [ -f "$(dirname "$0")/code" ]; then
  cp "$(dirname "$0")/code" "$PREFIX/code"
else
  curl -fsSL "$REPO_RAW" -o "$PREFIX/code"
fi
chmod +x "$PREFIX/code"
echo "Installed to $PREFIX/code"
case ":$PATH:" in *":$PREFIX:"*) ;; *) echo "Note: add $PREFIX to your PATH." ;; esac
if command -v code >/dev/null 2>&1 && [ "$(command -v code)" != "$PREFIX/code" ]; then
  echo "Warning: another 'code' ($(command -v code)) is earlier on your PATH (e.g. the VS Code shell command)."
fi
