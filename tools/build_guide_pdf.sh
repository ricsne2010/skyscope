#!/bin/sh
# Rebuild docs/SkyScope-Guide.pdf from docs/guide.html (the same page the app
# serves at /guide), so the two never drift apart. Needs Google Chrome or
# Chromium installed.
#
#   sh tools/build_guide_pdf.sh
set -e
cd "$(dirname "$0")/.."
for c in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
         "$(command -v google-chrome || true)" "$(command -v chromium || true)" "$(command -v chromium-browser || true)"; do
  if [ -n "$c" ] && [ -x "$c" ]; then CHROME="$c"; break; fi
done
[ -n "$CHROME" ] || { echo "Chrome or Chromium not found" >&2; exit 1; }
"$CHROME" --headless=new --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="$PWD/docs/SkyScope-Guide.pdf" "file://$PWD/docs/guide.html" 2>/dev/null
echo "wrote docs/SkyScope-Guide.pdf"
