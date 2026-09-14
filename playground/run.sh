#!/usr/bin/env bash
# Prompt Lab yerel dev sunucusunu başlatır (bash / Git Bash / macOS / Linux).
#
# Kullanım (repo kökünden):
#   ./playground/run.sh
#
# GEMINI_API_KEY'i mevcut ortamdan ya da repo kökündeki .env / .env.local'den
# bulur — asıl yükleme `playground/__init__.py` içinde olur (paket import
# edilir edilmez çalışır), bu yüzden `uvicorn playground.server:app` DOĞRUDAN
# çalıştırılsa bile anahtar bulunur. Bu script yalnızca kolaylık + erken uyarı
# sağlar. Anahtar yalnızca sunucu ortamında kalır; tarayıcıya gitmez.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

has_key=0
[ -n "${GEMINI_API_KEY:-}" ] && has_key=1
if [ "$has_key" = 0 ]; then
  for f in "$REPO_ROOT/.env" "$REPO_ROOT/.env.local"; do
    if [ -f "$f" ] && grep -qE '^\s*GEMINI_API_KEY\s*=' "$f"; then
      has_key=1
    fi
  done
fi

if [ "$has_key" = 0 ]; then
  echo "UYARI: GEMINI_API_KEY hicbir yerde bulunamadi (ortam degiskeni, .env, .env.local)." >&2
  echo "Repo KOKUNDE (web/ ALTINDA DEGIL) .env ya da .env.local dosyasina ekleyin:" >&2
  echo '  GEMINI_API_KEY="..."' >&2
  echo "Sunucu yine de acilir ama /playground/extract 503 doner." >&2
fi

cd "$REPO_ROOT"
exec python -m uvicorn playground.server:app --reload --port 8900
