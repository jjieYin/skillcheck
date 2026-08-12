#!/usr/bin/env sh
set -eu

REPOSITORY="${SKILLCHECK_REPOSITORY:-jjieYin/skillcheck}"
VERSION="${SKILLCHECK_VERSION:-latest}"
if [ "$VERSION" = "latest" ]; then
  VERSION="$(curl -fsSL "https://api.github.com/repos/$REPOSITORY/releases/latest" | sed -n 's/.*"tag_name": "v\{0,1\}\([^"]*\)".*/\1/p')"
fi

case "$(uname -s):$(uname -m)" in
  Linux:x86_64|Linux:amd64) PLATFORM=linux; ARCH=x64; EXT=tar.gz ;;
  Darwin:x86_64) PLATFORM=macos; ARCH=x64; EXT=tar.gz ;;
  Darwin:arm64) PLATFORM=macos; ARCH=arm64; EXT=tar.gz ;;
  *) echo "不支持的平台：$(uname -s) $(uname -m)" >&2; exit 2 ;;
esac

ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/skillcheck"
BIN="${HOME}/.local/bin"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
ASSET="skillcheck-${VERSION}-${PLATFORM}-${ARCH}.${EXT}"
BASE="https://github.com/${REPOSITORY}/releases/download/v${VERSION}"
DOWNLOAD_QUERY="?skillcheck_version=${VERSION}"
MANIFEST="manifest-${PLATFORM}-${ARCH}.json"
curl -fsSL "${BASE}/${ASSET}${DOWNLOAD_QUERY}" -o "${TMP}/${ASSET}"
curl -fsSL "${BASE}/${MANIFEST}${DOWNLOAD_QUERY}" -o "${TMP}/manifest.json"

EXPECTED="$(sed -n 's/.*"sha256": "\([a-fA-F0-9]*\)".*/\1/p' "${TMP}/manifest.json")"
ACTUAL="$(sha256sum "${TMP}/${ASSET}" 2>/dev/null | awk '{print $1}' || shasum -a 256 "${TMP}/${ASSET}" | awk '{print $1}')"
[ "$(printf '%s' "$EXPECTED" | tr '[:upper:]' '[:lower:]')" = "$(printf '%s' "$ACTUAL" | tr '[:upper:]' '[:lower:]')" ] || { echo "SHA-256 校验失败" >&2; exit 1; }

TARGET="${ROOT}/versions/${VERSION}"
if [ ! -d "$TARGET" ]; then
  mkdir -p "${ROOT}/versions"
  mkdir -p "$TARGET"
  tar -xzf "${TMP}/${ASSET}" -C "$TARGET"
fi
mkdir -p "$BIN"
cat > "${BIN}/skillcheck" <<EOF
#!/usr/bin/env sh
exec "${TARGET}/skillcheck" "\$@"
EOF
chmod +x "${BIN}/skillcheck"
case ":${PATH:-}:" in *":${BIN}:"*) ;; *) echo "请将 ${BIN} 加入 PATH" ;; esac
"${BIN}/skillcheck" version
if [ -t 0 ] && [ -t 1 ]; then
  "${BIN}/skillcheck" install
else
  echo "Release installed. Run skillcheck install in an interactive terminal to choose Agent targets."
fi
