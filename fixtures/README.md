# fixtures/ — etiketli test görselleri

Faz 1'in üç varsayımından ikisi (tanıma doğruluğu, kategori isabeti) bu kümeyle
ölçülecek. Hedef: **50 görsel.**

## Kurallar

- Görsellerin kendisi (`fixtures/images/`) **repoda tutulmaz** — `.gitignore`'da.
  Paylaşılan sürücüde durur. Sebep: repo boyutu ve KVKK.
- Etiketler (`labels.jsonl`) repoda tutulur ve doğruluk hesabının kaynağıdır.
- Sadece ekibin kendi çektiği görseller. Gerçek kullanıcı verisi yok, internetten
  indirilen telifli görsel yok.
- Fotoğrafta insan yüzü, kimlik belgesi veya adres görünmesin.

## `labels.jsonl` formatı

Satır başına bir görsel:

```json
{"image": "img_001.jpg", "foods": [{"name": "süt", "category": "dairy", "subcategory": "milk_fresh", "package_state": "unopened", "quantity": {"value": 1, "unit": "piece"}}]}
```

`category`, `subcategory` ve `package_state` değerleri `src/core/taxonomy.py`'deki
kapalı listeden gelmek zorundadır (küçük harf) — aksi halde ölçüm anlamsızlaşır.

## Dağılım hedefi

Tek kategoriye yığılmayın; en az 8 farklı kategori ve şu zorlukları içersin:
kısmen görünen ürün, birden fazla ürün aynı karede, buzdolabı içi düşük ışık,
şeffaf poşet içinde ürün, açılmış ambalaj.
