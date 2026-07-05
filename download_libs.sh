#!/usr/bin/env bash
set -Eeuo pipefail

# Download the latest prebuilt libraries for the current system from:
#   https://github.com/manx98/flow-test-libs-build/releases
#
# Usage:
#   bash download_libs.sh
#
# Optional overrides:
#   TARGET_OS=linux TARGET_ARCH=x86_64 bash download_libs.sh
#   LIBS_DIR=/path/to/libs bash download_libs.sh
#   GITHUB_TOKEN=ghp_xxx bash download_libs.sh   # for higher GitHub API rate limits
#   CLEAN_LIBS=0 bash download_libs.sh           # do not clean libs/ before extracting

REPO="manx98/flow-test-libs-build"
API_URL="https://api.github.com/repos/${REPO}/releases/latest"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIBS_DIR="${LIBS_DIR:-${ROOT_DIR}/libs}"
CLEAN_LIBS="${CLEAN_LIBS:-1}"

log() {
  printf '[download_libs] %s\n' "$*"
}

fail() {
  printf '[download_libs] ERROR: %s\n' "$*" >&2
  exit 1
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

detect_os() {
  local os
  os="$(uname -s | tr '[:upper:]' '[:lower:]')"
  case "$os" in
    linux*) echo "linux" ;;
    darwin*) echo "darwin" ;;
    msys*|mingw*|cygwin*) echo "windows" ;;
    *) fail "unsupported OS from uname -s: ${os}" ;;
  esac
}

detect_arch() {
  local arch
  arch="$(uname -m | tr '[:upper:]' '[:lower:]')"
  case "$arch" in
    x86_64|amd64) echo "x86_64" ;;
    aarch64|arm64) echo "aarch64" ;;
    armv7l|armv7*) echo "armv7" ;;
    i386|i486|i586|i686) echo "x86" ;;
    *) echo "$arch" ;;
  esac
}

contains_any() {
  local text="$1"
  shift
  local token
  for token in "$@"; do
    [[ "$text" == *"$token"* ]] && return 0
  done
  return 1
}

has_known_os_token() {
  local text="$1"
  contains_any "$text" linux darwin macos osx windows win32 win64 mingw msys cygwin
}

has_target_os_token() {
  local text="$1"
  case "$TARGET_OS" in
    linux) contains_any "$text" linux ;;
    darwin) contains_any "$text" darwin macos osx ;;
    windows) contains_any "$text" windows win32 win64 mingw msys cygwin ;;
    *) return 1 ;;
  esac
}

has_other_os_token() {
  local text="$1"
  case "$TARGET_OS" in
    linux) contains_any "$text" darwin macos osx windows win32 win64 mingw msys cygwin ;;
    darwin) contains_any "$text" linux windows win32 win64 mingw msys cygwin ;;
    windows) contains_any "$text" linux darwin macos osx ;;
    *) return 1 ;;
  esac
}

has_known_arch_token() {
  local text="$1"
  contains_any "$text" x86_64 amd64 x64 aarch64 arm64 armv7 armhf i386 i686 x86
}

has_target_arch_token() {
  local text="$1"
  case "$TARGET_ARCH" in
    x86_64) contains_any "$text" x86_64 amd64 x64 ;;
    aarch64) contains_any "$text" aarch64 arm64 ;;
    armv7) contains_any "$text" armv7 armhf ;;
    x86) contains_any "$text" i386 i686 x86 ;;
    *) contains_any "$text" "$TARGET_ARCH" ;;
  esac
}

has_other_arch_token() {
  local text="$1"
  case "$TARGET_ARCH" in
    x86_64) contains_any "$text" aarch64 arm64 armv7 armhf i386 i686 ;;
    aarch64) contains_any "$text" x86_64 amd64 x64 armv7 armhf i386 i686 ;;
    armv7) contains_any "$text" x86_64 amd64 x64 aarch64 arm64 i386 i686 ;;
    x86) contains_any "$text" x86_64 amd64 x64 aarch64 arm64 armv7 armhf ;;
    *) return 1 ;;
  esac
}

is_archive() {
  local name="$1"
  case "$name" in
    *.zip|*.tar.gz|*.tgz|*.tar.xz|*.txz|*.tar.bz2|*.tbz2) return 0 ;;
    *) return 1 ;;
  esac
}

fetch_latest_release_json() {
  local auth_header=()
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    auth_header=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
  fi

  if command_exists curl; then
    curl -fsSL --retry 3 --retry-delay 1 \
      -H "Accept: application/vnd.github+json" \
      "${auth_header[@]}" \
      "$API_URL"
  elif command_exists wget; then
    if [[ -n "${GITHUB_TOKEN:-}" ]]; then
      wget -qO- --header="Accept: application/vnd.github+json" --header="Authorization: Bearer ${GITHUB_TOKEN}" "$API_URL"
    else
      wget -qO- --header="Accept: application/vnd.github+json" "$API_URL"
    fi
  else
    fail "curl or wget is required"
  fi
}

extract_browser_download_urls() {
  # GitHub API JSON is simple enough here: release asset URLs are in browser_download_url fields.
  grep -o '"browser_download_url"[[:space:]]*:[[:space:]]*"[^"]*"' \
    | sed -E 's/^.*"browser_download_url"[[:space:]]*:[[:space:]]*"([^"]*)".*$/\1/'
}

download_file() {
  local url="$1"
  local out="$2"

  if command_exists curl; then
    curl -fL --retry 3 --retry-delay 1 -o "$out" "$url"
  elif command_exists wget; then
    wget -O "$out" "$url"
  else
    fail "curl or wget is required"
  fi
}

extract_archive() {
  local archive="$1"
  local dest="$2"

  case "$archive" in
    *.zip)
      command_exists unzip || fail "unzip is required to extract ${archive}"
      unzip -q -o "$archive" -d "$dest"
      ;;
    *.tar.gz|*.tgz)
      tar -xzf "$archive" -C "$dest"
      ;;
    *.tar.xz|*.txz)
      tar -xJf "$archive" -C "$dest"
      ;;
    *.tar.bz2|*.tbz2)
      tar -xjf "$archive" -C "$dest"
      ;;
    *)
      fail "unsupported archive format: ${archive}"
      ;;
  esac
}

TARGET_OS="${TARGET_OS:-$(detect_os)}"
TARGET_ARCH="${TARGET_ARCH:-$(detect_arch)}"

log "target system: ${TARGET_OS}/${TARGET_ARCH}"

release_json="$(fetch_latest_release_json)"
release_tag="$(printf '%s\n' "$release_json" | grep -o '"tag_name"[[:space:]]*:[[:space:]]*"[^"]*"' | head -n1 | sed -E 's/^.*"tag_name"[[:space:]]*:[[:space:]]*"([^"]*)".*$/\1/' || true)"
mapfile -t asset_urls < <(printf '%s\n' "$release_json" | extract_browser_download_urls)

[[ ${#asset_urls[@]} -gt 0 ]] || fail "no release assets found in latest release"
[[ -n "$release_tag" ]] && log "latest release: ${release_tag}"

matched_urls=()
for url in "${asset_urls[@]}"; do
  file_name="${url##*/}"
  file_name="${file_name%%\?*}"
  lower_name="$(printf '%s' "$file_name" | tr '[:upper:]' '[:lower:]')"

  is_archive "$lower_name" || continue
  has_other_os_token "$lower_name" && continue
  has_other_arch_token "$lower_name" && continue

  # Accept exact OS/arch matches and generic archives that do not contain OS/arch tokens.
  if { has_target_os_token "$lower_name" || ! has_known_os_token "$lower_name"; } && \
     { has_target_arch_token "$lower_name" || ! has_known_arch_token "$lower_name"; }; then
    matched_urls+=("$url")
  fi
done

if [[ ${#matched_urls[@]} -eq 0 ]]; then
  printf '[download_libs] available assets:\n' >&2
  printf '  %s\n' "${asset_urls[@]##*/}" >&2
  fail "no archive asset matches ${TARGET_OS}/${TARGET_ARCH}; override with TARGET_OS/TARGET_ARCH if needed"
fi

mkdir -p "$LIBS_DIR"
if [[ "$CLEAN_LIBS" == "1" ]]; then
  log "cleaning ${LIBS_DIR}"
  rm -rf "${LIBS_DIR:?}/"*
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

for url in "${matched_urls[@]}"; do
  file_name="${url##*/}"
  file_name="${file_name%%\?*}"
  archive_path="${tmp_dir}/${file_name}"

  log "downloading ${file_name}"
  download_file "$url" "$archive_path"

  log "extracting ${file_name} -> ${LIBS_DIR}"
  extract_archive "$archive_path" "$LIBS_DIR"
done

log "done: ${LIBS_DIR}"
