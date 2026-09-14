"""Prompt Lab — yerel, izole AI mühendisi çalışma ortamı.

Bu paket ÜRETİME GİTMEZ. `infra/scripts/build_lambda_packages.py` yalnızca
`src/`'i Lambda paketine kopyalar; bu paket repo kökünde durduğu için deploy
paketine hiç girmez ve `fastapi`/`uvicorn` gibi bağımlılıkları Lambda'ya
bulaştırmaz.

Amaç: prompt sürümlerini deneyip modele giden TAM prompt'u, token sayısını ve
tahmini maliyeti görmek. Üretim çıkarım mantığını (`core.extraction`,
`core.taxonomy`) OLDUĞU GİBİ tekrar kullanır; onu değiştirmez. Böylece Lab'da
gördüğün parse/şema davranışı üretimdekiyle birebir aynıdır.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

# `core` paketi `src/` altında. Bu paket repo kökünde olduğundan, `import core`
# çalışsın diye `src`'i yola ekliyoruz — PYTHONPATH ayarlanmamış olsa bile
# `uvicorn playground.server:app` repo kökünden çalışır.
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$")


def _parse_env_file(path: Path) -> dict[str, str]:
    """Basit `.env` ayrıştırıcı: `KEY=value` / `KEY="value"` / yorum satırları.

    `python-dotenv` bağımlılığı eklemeden (bu paket tamamen izole kalsın diye)
    aynı işi yapan minimal bir ayrıştırıcı. Tırnak işaretleri soyulur.
    """
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ENV_LINE_RE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def _load_dotenv_files() -> None:
    """Repo kökündeki `.env` ve `.env.local`'i oku, eksik ortam değişkenlerini doldur.

    Sunucu nasıl başlatılırsa başlatılsın (`playground/run.ps1`, `run.sh`, ya da
    doğrudan `uvicorn playground.server:app`) `GEMINI_API_KEY` bulunsun diye bu
    yükleme paket import edilir edilmez, tek yerden çalışır. Zaten kabukta
    ayarlı bir değişkenin ÜZERİNE YAZILMAZ — kabuk her zaman kazanır.
    `.env.local` (kişisel, gitignore'da) `.env`'in üzerine yazar; bu web/Vite'daki
    aynı `.env` < `.env.local` önceliğiyle tutarlıdır.
    """
    merged: dict[str, str] = {}
    merged.update(_parse_env_file(_REPO_ROOT / ".env"))
    merged.update(_parse_env_file(_REPO_ROOT / ".env.local"))
    for key, value in merged.items():
        os.environ.setdefault(key, value)


_load_dotenv_files()
