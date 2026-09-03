# Akıllı Buzdolabı — Görüntü Tabanlı Envanter (PoC)

Kullanıcı bir gıda fotoğrafı yükler. Sistem görseli bir görüntü anlayan modele
(Vision-LLM) gönderip **ürün adı + kategori** çıkarır, kategoriye göre **tahmini
tazelik tarihi** hesaplar ve sonucu envantere yazar. Tümü AWS ücretsiz katmanı
hedeflenerek, sunucusuz (serverless) bir mimariyle çalışır.

Bu bir kavram kanıtı (PoC) çalışmasıdır; üç varsayımı ölçer:

1. Model, özel eğitim olmadan gıdaları yeterli doğrulukta tanıyabiliyor mu?
2. Kategori bazlı tazelik tahmini anlamlı sonuç veriyor mu?
3. Bu akış AWS ücretsiz katmanında kabul edilebilir gecikmeyle çalışıyor mu?

---

## Mimari

Sistem tek yönlü, olay güdümlü (event-driven) bir akıştır: tarayıcı dosyayı
doğrudan S3'e yükler, S3 olayı asenkron çıkarım Lambda'sını tetikler, sonuç
DynamoDB'ye yazılır ve arayüz durumu sorgulayarak sonucu gösterir.

![Faz 1 akış diyagramı](docs/images/faz1-akis-diyagrami.png)

Ayrıntılı servis-servis boru hattı (istek numaralarıyla):

![Mimari boru hattı](docs/images/mimari-pipeline.png)

Özet akış:

```
Tarayıcı ──POST /v1/uploads──► API Gateway ──► fridge-api ──► presigned POST + upload_id
    │                                                              │
    └──dosyayı doğrudan S3'e──► s3://fridge-raw-*/uploads/  ◄───────┘
                                          │
                            ObjectCreated (prefix: uploads/)
                                          ▼
                                   fridge-extractor
                                     │          │
                              Gemini 2.5     DynamoDB (Observation + InventoryItem)
                                          ▲
    Tarayıcı ──GET /v1/uploads/{id}───────┘   (~2 sn'de bir sorar)
```

### Neden bu tasarım

| Karar | Gerekçe |
|---|---|
| Görsel **doğrudan** S3'e (API Gateway'den geçmez) | 5 MB'lık dosya Lambda payload limitini aşar; presigned POST boyut ve içerik tipini de sınırlar. |
| Çıkarım **asenkron** (S3 → Lambda) | LLM çağrısı saniyeler sürebilir; senkron API isteği zaman aşımına uğrardı. |
| Tarih **modelden değil, kuraldan** | Model tarih üretmez; tazelik `fotoğraf_tarihi + raf_ömrü(kategori)` ile hesaplanır. Sonuç bir tahmindir, SKT/TETT değildir. |
| DynamoDB **tek tablo + GSI1** | Tüm erişim `query`/`get_item` ile yapılır, `scan` yoktur; ücretsiz katmanda öngörülebilir maliyet. |
| SQS **sadece DLQ** | Kuyruk akışın içinde değil, kenarında; başarısız çıkarımlar için `onFailure` hedefi. |

### Kurulan AWS kaynakları

| Kaynak | Ad | Kritik ayarlar |
|---|---|---|
| S3 Bucket | `fridge-raw-{hesap}` | Public access kapalı, SSE-S3, CORS, 30 gün lifecycle, `ObjectCreated:*` → Lambda (prefix `uploads/`) |
| HTTP API | `fridge-api-gw` | Auth yok, throttling 5 rps / burst 10, CORS kısıtlı |
| Lambda | `fridge-api` | 256 MB, 10 sn, arm64 |
| Lambda | `fridge-extractor` | 512 MB, 60 sn, arm64, reserved concurrency 5, onFailure → DLQ |
| DynamoDB | `fridge-main` | Provisioned 5/5, GSI1 5/5, TTL `expires_at`, Streams açık |
| SSM Parameter | `/smartfridge/dev/gemini-api-key` | SecureString (elle oluşturulur) |
| SQS | `fridge-extractor-dlq` | 14 gün saklama |
| Log Groups | ×3 | retention 7 gün |
| IAM Roles | ×2 | Kaynak bazlı, wildcard yok |
| Budget | 5 USD | E-posta alarmı |

Altyapının nasıl kurulduğu ve deploy adımları: [`infra/README.md`](infra/README.md).

---

## Proje yapısı

```
.
├── src/
│   ├── core/          # Saf iş mantığı — AWS importu yok, AWS olmadan test edilir
│   ├── adapters/      # VisionProvider (Gemini) + InventoryRepository (DynamoDB)
│   └── handlers/      # Lambda giriş noktaları — ince; event parse et, core'u çağır
├── infra/             # AWS CDK stack'i (Python) + Lambda paketleme scripti
├── web/               # React + Vite + TypeScript test arayüzü
├── tests/
│   ├── unit/          # core/ testleri, AWS gerektirmez
│   └── integration/   # moto ile sahte AWS testleri
├── fixtures/          # Etiketli test görselleri (görseller versiyonlanmaz)
└── docs/              # Görseller ve kaynak veriler
```

Katman kuralı tek yönlüdür: `handlers` ve `adapters`, `core`'a bağımlıdır; `core`
hiçbir şeye bağımlı değildir ve içinde AWS importu bulunamaz. Bu kural
`tests/unit/test_core_purity.py` tarafından otomatik zorlanır.

---

## Kurulum

Gerekenler: Python 3.12+, Node 20+ (CDK ve web arayüzü için), AWS kimlik profili.

### Backend (iş mantığı + testler)

```bash
python -m venv .venv && source .venv/Scripts/activate
pip install -r requirements-dev.txt -r requirements.txt
```

Lint ve testler:

```bash
ruff check . && ruff format --check .
pytest tests/unit                          # AWS gerektirmez, saniyeler sürer
pytest tests/integration -m integration    # moto ile sahte AWS
```

### Web arayüzü

```bash
cd web && npm install && npm run dev   # http://localhost:5173
```

Ayrıntı: [`web/README.md`](web/README.md).

### Altyapı (deploy)

```bash
pip install -r infra/requirements.txt
python infra/scripts/build_lambda_packages.py
cd infra && cdk synth -c budget_alert_email=ekip@ornek.com
```

Tam deploy akışı ve konsol adımları: [`infra/README.md`](infra/README.md).

---

## Sırlar

Gemini API anahtarı repoda, `.env`'de veya Lambda ortam değişkeninde **durmaz**.
SSM Parameter Store SecureString'te durur ve elle oluşturulur:

```bash
aws ssm put-parameter --name /smartfridge/dev/gemini-api-key --type SecureString --value "ANAHTAR" --region eu-central-1
```

Lambda ortam değişkeni anahtarın **kendisini** değil, **parametre adını** taşır.

---

## Dal stratejisi ve CI/CD

Depo Gitflow'a göre işletilir:

| Dal | Amaç |
|---|---|
| `main` | Kararlı, yayınlanabilir sürüm. Doğrudan push yapılmaz. |
| `develop` | Entegrasyon dalı; özellikler burada birleşir. |
| `feature/*` | Tek bir iş; `develop`'tan açılır, `develop`'a PR ile döner. |
| `release/*` | Yayın hazırlığı; `develop`'tan açılır, `main` ve `develop`'a birleşir. |
| `hotfix/*` | Acil düzeltme; `main`'den açılır, `main` ve `develop`'a birleşir. |

Her push ve `main`/`develop`'a açılan her PR, GitHub Actions'ta CI çalıştırır:
lint (ruff), birim testleri, entegrasyon testleri (moto) ve CDK synth. Ayrıntı
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) dosyasında.
