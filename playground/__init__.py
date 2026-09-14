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

import sys
from pathlib import Path

# `core` paketi `src/` altında. Bu paket repo kökünde olduğundan, `import core`
# çalışsın diye `src`'i yola ekliyoruz — PYTHONPATH ayarlanmamış olsa bile
# `uvicorn playground.server:app` repo kökünden çalışır.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
