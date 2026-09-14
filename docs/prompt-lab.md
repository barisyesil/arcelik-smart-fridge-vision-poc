# Prompt Lab — AI mühendisi çalışma ortamı

Prompt Lab, buzdolabı görsel çıkarım promptunu **üretimden bağımsız** deneyip
ölçmek için kurulan yerel bir araçtır. Amaç: farklı prompt sürümlerini denemek,
modele giden **tam prompt'u**, **token sayısını** ve **tahmini maliyeti** görmek.

> Lab üretim mimarisine dokunmaz. Gerçek çıkarım hâlâ asenkron akışla çalışır
> (S3 → Lambda `extractor` → Gemini → DynamoDB) ve mobil ile web hep **üretim
> promptunu** (`core.extraction.SYSTEM_PROMPT`, `PROMPT_VERSION`) kullanır. Lab
> yalnızca ayrı bir yerel FastAPI sunucusu + web'de ayrı bir ekrandır.

## Mimari

```
Tarayıcı (web/#lab)  ──►  playground/server.py (FastAPI, localhost:8900)  ──►  Gemini
   PromptLab.tsx            /playground/extract                                  |
   usePromptLab.ts          core.extraction (şema + parse)  ◄────────────────────┘
                            core.taxonomy (birimler/kategoriler)
```

- **`core` yeniden kullanılır, değiştirilmez.** Lab, üretimle **birebir aynı**
  `build_response_schema()` ve `parse_extraction()`'ı çağırır. Yani Lab'da
  gördüğün ürün yapısı üretimdekiyle aynıdır; yalnızca *sistem promptu metni*
  değişir. Bu, prompt karşılaştırmasını elmayla elma yapar.
- **İzolasyon:** Lab Cognito/DynamoDB/S3 tanımaz. `playground/` paketi repo
  kökündedir; `infra/scripts/build_lambda_packages.py` yalnızca `src/`'i
  paketlediği için Lab kodu Lambda'ya **hiç girmez**.

## Kurulum

Dev bağımlılıkları (FastAPI/uvicorn) `requirements-dev.txt` içindedir:

```bash
pip install -r requirements-dev.txt
```

`GEMINI_API_KEY`'i repo kökündeki `.env` dosyasına ekle (bkz. `.env.example`).
Anahtar sunucu tarafında kalır; tarayıcıya **asla** gönderilmez.

## Çalıştırma

**1) Yerel Lab sunucusu** (repo kökünden):

```bash
# Windows PowerShell
.\playground\run.ps1

# bash / Git Bash / macOS / Linux
./playground/run.sh

# ya da doğrudan
uvicorn playground.server:app --reload --port 8900
```

**2) Web arayüzü** (`web/` dizininden):

```bash
npm run dev
```

Tarayıcıda web'i aç, sağ üstteki **🧪 Prompt Lab** bağlantısına tıkla (veya
adrese `#lab` ekle: `http://localhost:5173/#lab`). Lab, giriş/Cognito
gerektirmez — auth gate'lerinden önce açılır.

## Kullanım

1. **Prompt sürümü seç.** Liste başında ★ ile üretim promptu (referans,
   düzenlenemez), ardından deney varyantları ve senin kaydettiklerin gelir.
2. **Düzenle.** Metni değiştirince "düzenlendi" işaretlenir; Çalıştır bu ham
   metni gönderir. Kalıcı yapmak için **Yeni sürüm olarak kaydet**.
3. **Görsel seç, Çalıştır.** Sonuç panelinde:
   - Süre, ürün grubu sayısı, **token** (girdi/çıktı/toplam), **tahmini maliyet**
   - Ürün grupları: ad, **sayı/aralık + birim**, kategori, güven, kutu durumu
   - Görsel üzerine çizili **grup kutuları** (0–1000 ölçeği)
   - Açılır bloklar: **modele giden tam sistem promptu**, ham JSON yanıt, şema
4. **Karşılaştır.** Aynı görselle farklı sürümleri çalıştırıp token/maliyet ve
   sayım/gruplama kalitesini kıyasla.

Kaydettiğin sürümler `playground/prompt_versions.json`'a yazılır (`.gitignore`'da
— her mühendisin deney seti kendine özeldir).

## Fiyatlandırma notu

`playground/pricing.py`'daki fiyatlar **tahminidir** ve zamanla değişir; tahmini
maliyet göstermek içindir, faturalandırma için değil. Güncel değerleri
[Gemini fiyatlandırma](https://ai.google.dev/gemini-api/docs/pricing) sayfasından
doğrulayıp tabloyu güncelle.

## Sonraki adım: üretim promptunu güncellemek

Lab'da bir sürümü beğenip üretime almak istediğinde, metni
`src/core/extraction.py` içindeki `SYSTEM_PROMPT`'a taşı ve `PROMPT_VERSION`'ı
artır (ör. `v3` → `v4`). Böylece her `Observation` kaydı hangi promptla
üretildiğini taşır ve doğruluk ölçümü sürümleri karıştırmaz. Mobil ve Lambda
otomatik olarak yeni promptu kullanır.
