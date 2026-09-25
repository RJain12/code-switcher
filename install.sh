#!/usr/bin/env sh
# Default installs use paired, atomic releases. PREFIX retains a portable install.
set -e
if [ -z "${PREFIX:-}" ]; then
  if [ -f "$(dirname "$0")/codespace" ]; then
    exec python3 "$(dirname "$0")/codespace" update --install
  fi
  installer_dir="$(mktemp -d)"
  trap 'rm -rf "$installer_dir"' EXIT HUP INT TERM
  curl -fsSL "https://raw.githubusercontent.com/RJain12/code-switcher/main/codespace" -o "$installer_dir/codespace"
  python3 "$installer_dir/codespace" update --install
  exit
fi
mkdir -p "$PREFIX"
installer_dir="$(mktemp -d "$PREFIX/.codespace-install.XXXXXX")"
trap 'rm -rf "$installer_dir"' EXIT HUP INT TERM
for entry in code codespace; do
  if [ -f "$(dirname "$0")/$entry" ]; then
    cp "$(dirname "$0")/$entry" "$installer_dir/$entry"
  else
    curl -fsSL "https://raw.githubusercontent.com/RJain12/code-switcher/main/$entry" -o "$installer_dir/$entry"
  fi
  chmod +x "$installer_dir/$entry"
done
for entry in code codespace; do
  mv -f "$installer_dir/$entry" "$PREFIX/$entry"
done
echo "Installed portable CLIs to $PREFIX"
