# web/ — test arayüzü

React + Vite + TypeScript. Backend'i elle tıklamadan doğrulamak için bir test
aracı; API kontratı v1'in **tüm** uçlarını kullanır — kimlik doğrulama, profil
kaydı, envanter, swipe aksiyonları, tazelik değerlendirmesi, kontrol kuyruğu,
alışveriş listesi, yeniden alma önerileri, tarifler.

## Çalıştırma

```bash
cd web
npm install
npm run dev
```

`http://localhost:5173` açılır.

1. **Bağlantı ayarları** panelinden API adresi + Cognito domain/client ID gir
   (`cdk deploy` çıktıları — bkz. [`infra/README.md`](../infra/README.md)
   "Web arayüzü yapılandırması"). `.env` içinde `VITE_API_URL`,
   `VITE_COGNITO_DOMAIN`, `VITE_COGNITO_CLIENT_ID` ile varsayılan da
   verilebilir (bkz. `.env.example`). Bu değerler tarayıcıda `localStorage`'da
   tutulur.
2. **Cognito ile giriş yap / kaydol.** Amazon Cognito Hosted UI'a
   yönlendirilirsin; şifren bu uygulamadan geçmez (Authorization Code + PKCE,
   secretsız public client).
3. **Profil oluştur.** İlk girişte Ad-Soyad + buzdolabı ID'si istenir; ID
   `cdk deploy` çıktısındaki `SeedFridgeIds` listesinden biri olmalı. Veri bu
   buzdolabı bazında paylaşılır (hane modeli) — aynı ID ile kaydolan başka
   kullanıcılar aynı envanteri görür.

## Akış

1. Fotoğraf seçilir → tarayıcıda **1024px / JPEG q80'e küçültülür**.
2. `POST /v1/uploads` → presigned POST alanları.
3. Dosya **doğrudan S3'e** yüklenir (API Gateway'den geçmez).
4. `GET /v1/uploads/{id}` ~2 saniyede bir sorgulanır; tamamlanınca bulunan
   ürünler Gemini'nin verdiği sınırlayıcı kutulara göre kaynak fotoğraftan
   kırpılıp ("Çıkarım sonucu" bölümü) ayrı ayrı gösterilir.
5. Envanter listesi yenilenir.

### Sekmeler

| Sekme | İçerik |
|---|---|
| **Ürünlerim** | Envanter grid'i; her kart üzerinde Tükettim/Attım/Kontrol Et/Düzelt/Sil |
| **Kontrol** | Kontrol kuyruğu (BR-003/BR-004 önceliğiyle) — mobildeki swipe modunun web karşılığı |
| **Listem** | Bekleyen yeniden alma önerileri (kabul/geç) + aktif/tamamlanan alışveriş listesi |
| **Tarifler** | Stok uyumlu, deterministik skorlu tarif önerileri |

**Tükettim** / **Attım** butonları doğrudan `PATCH` değil, `POST
/v1/items/{id}/actions` çağırır (idempotent, sunucu tarafında `SwipeAction` +
`ReplacementCandidate` üretir). İşlemden sonra ~8 saniye **Geri Al** seçeneği
alttaki bildirimde belirir (BR-007). **Kontrol Et**, sistem tahminini ASLA
ezmeyen bir tazelik değerlendirmesi paneli açar (BR-009).

## Bilinmesi gerekenler

- `predicted_fresh_until` sistem tahminidir, **asla** ezilmez. Kullanıcı
  değerlendirmesi `user_adjusted_fresh_until` alanına ayrı yazılır; sıralamada
  kullanılan `effective_fresh_until` ikisinden biridir (BR-002). Arayüzde "son
  tüketim tarihi" veya "SKT" yazılmaz.
- `category`/`subcategory`/`package_state` API'den İngilizce küçük harf gelir
  (`src/core/taxonomy.py`, kapalı enum). `src/lib/labels.ts` bunu Türkçeye
  çevirir — sadece sunum katmanı, API kontratını etkilemez.
- Kimlik **yalnızca** Cognito `id_token`'ından gelir (`Authorization: Bearer`).
  Token `sessionStorage`'da tutulur (sekme kapanınca silinir); süresi
  dolduğunda `refresh_token` ile sessizce tazelenir.
- Backend CORS'u yalnızca `http://localhost:5173`'e açıktır; başka bir
  port/origin'den çalıştırırsan hem CORS hem Cognito callback allowlist'i
  reddeder.

## Yapı

```
src/
  api/          # types.ts (API kontratı), client.ts (fetch sarmalayıcı), auth.ts (Cognito OAuth)
  hooks/
    useAuth              # Cognito PKCE oturumu (login/logout/token tazeleme)
    useSettings          # API adresi + Cognito domain/client (localStorage)
    useProfile           # Profil okuma + kayıt (Ad-Soyad + fridge ID)
    useInventory         # Envanter listesi + düzeltme/silme
    useUpload            # Presigned upload + durum takibi
    useSwipeActions      # Tükettim/Attım/Kontrol Et + 8sn geri al penceresi
    useReviewQueue       # Kontrol kuyruğu
    useShopping          # Alışveriş listesi (aktif/tamamlanan)
    useCandidates        # Bekleyen yeniden alma önerileri
    useRecipes           # Tarif önerileri
  components/   # AuthGate, ProfileSetup, AccountBar, SettingsBar, UploadPanel,
                # ExtractionResult, InventoryList, ItemCard, ReviewQueuePanel,
                # ShoppingPanel, RecipesPanel, AssessmentModal, UndoToast, Disclaimer
  lib/          # pkce (RFC 7636), resizeImage, cropImage (CSS kırpma), labels, freshness
```

## Kalite kontrolleri

```bash
npx tsc -b        # tip kontrolü
npm run build     # üretim derlemesi
npm run lint      # oxlint
```
