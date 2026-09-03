# web/ — test arayüzü

React + Vite + TypeScript. Backend'i elle tıklamadan doğrulamak için basit bir
arayüz; API kontratı v1'in tüm uçlarını kullanır (`POST /v1/uploads`,
`GET /v1/uploads/{id}`, `GET /v1/items`, `PATCH`/`DELETE /v1/items/{id}`).

## Çalıştırma

```bash
cd web
npm install
npm run dev
```

`http://localhost:5173` açılır. İlk açılışta üstteki **Bağlantı ayarları**
panelinden API adresini gir — `cdk deploy` çıktısındaki `ApiUrl`. Bu değer
tarayıcıda `localStorage`'da tutulur; istersen `.env` içinde `VITE_API_URL` ile
varsayılan da verebilirsin (bkz. `.env.example`).

## Akış

1. Fotoğraf seçilir → tarayıcıda **1024px / JPEG q80'e küçültülür** (S3
   depolamayı, Gemini token maliyetini ve yükleme süresini birden düşürür).
2. `POST /v1/uploads` → presigned POST alanları.
3. Dosya **doğrudan S3'e** yüklenir (API Gateway'den geçmez).
4. `GET /v1/uploads/{id}` ~2 saniyede bir sorgulanır, ~60 saniye sonra vazgeçilir.
5. Tamamlanınca envanter listesi yenilenir.

Envanter kartları tazelik tarihine göre renklenir (kırmızı: geçmiş/bugün, sarı:
≤2 gün, yeşil: ötesi). Güven skoru düşük ürünler ayrıca "gözden geçirilmeli"
olarak işaretlenir.

## Bilinmesi gerekenler

- `estimated_freshness_date` bir **tahmindir**. Arayüzde "son tüketim tarihi"
  veya "SKT" yazılmaz; her ekranda görünen uyarı banner'ı bunu belirtir.
- `category`/`subcategory`/`package_state` API'den İngilizce küçük harf gelir
  (`src/core/taxonomy.py`, kapalı enum). `src/lib/labels.ts` bunu Türkçeye
  çevirir — sadece sunum katmanı, API kontratını etkilemez.
- Her istekte `x-user-id` header'ı gönderilir (Bağlantı ayarları panelinde
  değiştirilebilir). Kimlik doğrulama yoktur.
- Backend CORS'u yalnızca `http://localhost:5173`'e açıktır; başka bir
  port/origin'den çalıştırırsan istekler reddedilir.

## Yapı

```
src/
  api/          # types.ts (API kontratının TS karşılığı), client.ts (fetch sarmalayıcı)
  hooks/        # useSettings, useInventory, useUpload — durum yönetimi
  components/   # SettingsBar, UploadPanel, InventoryList, ItemCard, Disclaimer
  lib/          # resizeImage (küçültme), labels (TR çeviri), freshness (aciliyet hesabı)
```

## Kalite kontrolleri

```bash
npx tsc -b        # tip kontrolü
npm run build     # üretim derlemesi
npm run lint      # oxlint
```
