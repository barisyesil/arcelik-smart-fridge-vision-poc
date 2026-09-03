# Entegrasyon testleri

Buradaki testler `moto` ile sahte AWS servisleri kullanır — gerçek hesaba
bağlanmaz, para harcamaz. Makinede gerçek AWS kimlik bilgileri olsa bile
`moto` HTTP çağrılarını yakalar; hiçbir istek gerçek AWS'e ulaşmaz. Yine de
`@pytest.mark.integration` ile işaretlidir — CI'da `tests/unit`'ten ayrı bir
adım olarak çalışır (bkz. `.github/workflows/ci.yml`).

| Dosya | Kapsam |
|---|---|
| `conftest.py` | `fridge-main` şemasıyla sahte tablo + bucket kuran fixture'lar |
| `test_repository.py` | `DynamoRepository`: idempotency kilidi, atomik `commit_extraction`, GSI1 sparse davranışı, `update_item`/`delete_item` |
| `test_handlers.py` | Üç handler'ın uçtan uca akışı: presign → S3 olayı → extractor → inventory_api (CRUD) |

## Neden `importlib.reload` kullanılıyor

Handler modülleri `TABLE_NAME`/`BUCKET_NAME` gibi ortam değişkenlerini
**modül seviyesinde** (import anında) okur — bu Lambda'da bilinçli bir
tercih (soğuk başlatma dışında yeniden okumamak, bkz. `handlers/presign.py`).
Testte bu değerleri tazelemek için `handlers` fixture'ı (`test_handlers.py`)
env değişkenlerini `mock_aws()` aktifken ayarlayıp modülleri
`importlib.reload` ile yeniden çalıştırır.

## Çalıştırma

```bash
pytest tests/integration -m integration
```
