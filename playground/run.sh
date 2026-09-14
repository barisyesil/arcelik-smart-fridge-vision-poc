#!/usr/bin/env bash
# Prompt Lab yerel dev sunucusunu başlatır (bash / Git Bash / macOS / Linux).
#
# Kullanım (repo kökünden):
#   ./playground/run.sh
#
# GEMINI_API_KEY'i mevcut ortamdan ya da repo kökündeki .env'den okur. Anahtar
# yalnızca sunucu ortamında kalır; tarayıcıya gitmez.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -z "${GEMINI_API_KEY:-}" ] && [ -f "$REPO_ROOT/.env" ]; then
  # .env'deki GEMINI_API_KEY satırını dışa aktar (yorumları yok say).
  line="$(grep -E '^\s*GEMINI_API_KEY\s*=' "$REPO_ROOT/.env" | tail -1 || true)"
  if [ -n "$line" ]; then
    export GEMINI_API_KEY="$(echo "${line#*=}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//;s/^"//;s/"$//')"
  fi
fi

if [ -z "${GEMINI_API_KEY:-}" ]; then
  echo "UYARI: GEMINI_API_KEY ayarlı değil. Sunucu açılır ama /extract 503 döner." >&2
fi

cd "$REPO_ROOT"
exec python -m uvicorn playground.server:app --reload --port 8900
