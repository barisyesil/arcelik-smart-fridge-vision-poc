# Mobil (Kotlin) ↔ Cloud Entegrasyon Planı

**Belge sürümü:** 1.0
**Referans backend sürümü:** `feature/mobile-cloud-architecture` dalı, bu commit
**Referans SRS:** `arcelik-smart-fridge-mobile-srs.md` (Native Android, Kotlin/Compose)
**Hedef okuyucu:** Mobil (Kotlin) entegrasyonunu yapacak geliştirici/ajan (Codex)

Bu belge, local-first/mock mobil prototipin bu repodaki cloud backend'e
bağlanması için gereken **her şeyi** tek yerde toplar: kimlik doğrulama,
buzdolabı (hane) modeli, tüm endpoint'lerin tam sözleşmesi, Kotlin repository
arayüzü eşlemesi, senkronizasyon/idempotency kuralları ve bilinen sınırlamalar.

---

## 1. Mimari özet

```
Kotlin app (Compose)
  ↓ (Authorization Code + PKCE, public client)
Amazon Cognito User Pool  →  id_token (JWT, sub claim = kullanıcı kimliği)
  ↓ (Authorization: Bearer <id_token>)
API Gateway HTTP API (JWT authorizer)
  ↓
Lambda fridge-api  →  DynamoDB fridge-main (tek tablo, FRIDGE#{id} partition)
                  ↘  S3 fridge-raw-{account} (presigned upload/GET)

Lambda fridge-extractor  →  Gemini 2.5 Flash  →  DynamoDB (atomik yazım)
```

Önemli mimari kararlar (mobil entegrasyonunu doğrudan etkiler):

- **Kimlik yalnızca JWT'den gelir.** `x-user-id` header'ı üretimde **yok
  sayılır**. Backend `AUTH_MODE=jwt` ile çalışır; kimlik daima doğrulanmış
  `id_token`'ın `sub` claim'inden okunur.
- **Veri buzdolabı bazında paylaşılır (hane modeli).** Kullanıcının verisi
  değil, **kullanıcının kayıtlı olduğu buzdolabının** verisi vardır. Aynı
  buzdolabı ID'sine kayıtlı birden fazla kullanıcı aynı envanteri, alışveriş
  listesini, kontrol kuyruğunu ve önerileri görür/değiştirir. Profil, cihaz
  kaydı ve bildirim tercihi kullanıcıya özeldir.
- **Ürün görseli kırpma şu an istemci tarafındadır.** Backend her ürün için
  Gemini'nin verdiği sınırlayıcı kutuyu (`bounding_box`, 0-1000 normalize)
  döner + kaynak fotoğrafın kısa ömürlü presigned GET URL'sini verir.
  Kırpmayı (Canvas/Bitmap ile) istemci yapar. Bkz. §8.
- **Push bildirim gönderimi henüz yok.** Cihaz kaydı ve tercih endpoint'leri
  hazır; gerçek FCM/SNS gönderimi sonraki fazdadır. Mobil, günlük özeti şimdilik
  kendi `WorkManager`'ıyla üretmeye devam etmelidir (bkz. §9).

---

## 2. Kimlik doğrulama (Cognito, Authorization Code + PKCE)

### 2.1 Deploy'dan alınacak değerler

`cdk deploy` çıktılarından (`infra/README.md`):

| CDK çıktısı | Kotlin tarafında karşılığı |
|---|---|
| `UserPoolId` | Cognito SDK / AppAuth yapılandırması (opsiyonel, Hosted UI kullanılıyorsa gerekmeyebilir) |
| `UserPoolClientId` | **Mobil** app client ID — `WebTestClientId` DEĞİL |
| `CognitoDomain` | Hosted UI taban URL'si, örn. `https://fridge-123456789012.auth.eu-central-1.amazoncognito.com` |
| `ApiUrl` | Tüm `/v1/*` isteklerinin base URL'si |
| `SeedFridgeIds` | Prototipte kayıt için kullanılabilecek geçerli buzdolabı ID'leri |

Mobil client **public**'tir (secret YOK, `generate_secret=False`) — SRS
NFR-SEC-001 ile uyumlu, APK/AAB içinde hiçbir zaman client secret bulunmaz.

### 2.2 Callback (deep link)

Mobil client'ın callback/logout URL'leri CDK'da şu şekilde tanımlıdır:

```
callback_urls = ["arcelikfridge://auth"]
logout_urls   = ["arcelikfridge://signout"]
```

`AndroidManifest.xml`'de bu şema için bir intent-filter (deep link) tanımlanmalı.
Farklı bir şema/host kullanmak istenirse **önce infra tarafında** (bu repoda,
`infra/stacks/fridge_stack.py` → `MobileClient` → `callback_urls`/`logout_urls`)
güncellenip yeniden deploy edilmesi gerekir — aksi halde Cognito
`redirect_mismatch` hatası döner.

### 2.3 Akış (Authorization Code + PKCE)

1. `code_verifier` üret (43-128 karakter, `[A-Za-z0-9-._~]`, kriptografik
   rastgele — örn. 32 byte `SecureRandom` + base64url).
2. `code_challenge = BASE64URL(SHA256(code_verifier))`.
3. Tarayıcıya (Custom Tabs / AppAuth) şu URL'i aç:
   ```
   {CognitoDomain}/oauth2/authorize
     ?client_id={UserPoolClientId}
     &response_type=code
     &scope=openid+email+profile
     &redirect_uri=arcelikfridge://auth
     &code_challenge={code_challenge}
     &code_challenge_method=S256
     &state={rastgele-csrf-degeri}
   ```
4. Kullanıcı Hosted UI'da kaydolur/giriş yapar; Cognito `arcelikfridge://auth?code=...&state=...` ile geri döner.
5. `state` doğrulanır (giden değerle eşleşmeli), sonra token değişimi:
   ```
   POST {CognitoDomain}/oauth2/token
   Content-Type: application/x-www-form-urlencoded

   grant_type=authorization_code
   &client_id={UserPoolClientId}
   &code={code}
   &redirect_uri=arcelikfridge://auth
   &code_verifier={code_verifier}
   ```
   Yanıt: `{ id_token, access_token, refresh_token, expires_in, token_type }`.
6. **API çağrılarında `id_token` kullanılır** (`Authorization: Bearer
   {id_token}`) — `access_token` değil. API Gateway JWT authorizer, audience'ı
   user pool client ID'lerine göre doğrular; ID token'ın `aud` claim'i buna
   uyar.
7. `id_token` süresi dolmadan önce (`expires_in` saniye, tipik 1 saat) sessizce
   tazele:
   ```
   POST {CognitoDomain}/oauth2/token
   grant_type=refresh_token&client_id={UserPoolClientId}&refresh_token={refresh_token}
   ```
   Cognito yeni bir `refresh_token` döndürmez — eskisini sakla.
8. Çıkış: yerel token'ları sil + `{CognitoDomain}/logout?client_id={UserPoolClientId}&logout_uri=arcelikfridge://signout`.

**Referans implementasyon:** Bu repodaki web test aracı **aynı akışı**
tarayıcıda (public client + PKCE) uygular — `web/src/api/auth.ts` (URL
inşası, token değişimi/tazeleme) ve `web/src/hooks/useAuth.ts` (durum
yönetimi, callback işleme). PKCE S256 hesaplaması RFC 7636 Ek B test
vektörüyle doğrulanmıştır. Kotlin tarafında **AppAuth-Android** kütüphanesi
bu akışı (authorize/token/refresh/PKCE) hazır olarak sağlar; sıfırdan
yazmak yerine onu kullanmanız önerilir.

### 2.4 Token güvenliği

- Token'lar **EncryptedSharedPreferences** veya Android Keystore destekli bir
  depoda tutulmalı — düz `SharedPreferences` DEĞİL.
- Token, presigned URL ve kişisel veri **loglanmaz** (SRS NFR-SEC-003).
- 401 yanıtında: önce `refresh_token` ile bir kez tazele, tazeleme de
  başarısızsa oturumu kapat ve yeniden girişe yönlendir.

---

## 3. Buzdolabı (hane) modeli ve kayıt akışı

Kayıt, giriş yapıldıktan **sonra**, ilk `GET /v1/users/me` çağrısı 404
döndüğünde tetiklenir:

```
GET /v1/users/me
→ 404 { "error": "profile_not_found" }   // profil hiç oluşturulmamış
```

Kullanıcıdan **Ad-Soyad** + **buzdolabı ID**'si alınır (prototipte
`SeedFridgeIds` çıktısındaki değerlerden biri, örn. `ARC-FRIDGE-001`), sonra:

```
PUT /v1/users/me
{ "display_name": "Ayşe Yılmaz", "fridge_id": "ARC-FRIDGE-001" }

→ 201 (yeni profil) veya 200 (mevcut profil güncellendi)
{
  "user_id": "<cognito-sub>",
  "fridge_id": "ARC-FRIDGE-001",
  "display_name": "Ayşe Yılmaz",
  "created_at": "2026-09-11T10:00:00Z",
  "updated_at": "2026-09-11T10:00:00Z",
  "notification_preferences": {
    "mode": "DAILY_DIGEST",
    "digest_time": "18:30",
    "quiet_hours_start": "22:00",
    "quiet_hours_end": "08:00",
    "timezone_id": "Europe/Istanbul"
  }
}
```

Geçersiz/tanınmayan buzdolabı ID'si:

```
→ 400 { "error": "invalid_fridge_id", "fridge_id": "..." }
```

**Profil kaydı olmadan hiçbir veri isteği çalışmaz** — backend `409
profile_required` döner:

```
→ 409 { "error": "profile_required", "detail": "Önce profil oluşturun." }
```

Kotlin tarafı: uygulama açılışında `GET /v1/users/me` çağır; 404 ise kayıt
ekranını göster, 200 ise `fridge_id`'yi ve tercihleri local'e cache'le (ama
her isteğin kimliği yine backend'de JWT+profil ile çözülür — istemci
`fridge_id`'yi API isteklerine göndermez, yalnızca UI'da gösterir).

---

## 4. Ortak kurallar

### 4.1 Hata biçimi

Tüm hatalar `{"error": "<makine_kodu>", "detail"?: "<insan_okur_metin>"}`
biçimindedir. HTTP durumu anlamlıdır:

| Durum | Anlamı |
|---|---|
| 400 | Geçersiz alan değeri / eksik zorunlu alan / geçersiz buzdolabı ID |
| 401 | Kimlik doğrulanamadı (JWT yok/geçersiz) |
| 404 | Kaynak yok (item, upload, candidate, shopping item, profil) |
| 409 | Çakışma (profil eksik, öneri zaten kabul/reddedilmiş) |
| 204 | Başarılı, gövde yok (DELETE) |

### 4.2 Idempotency

- **Swipe aksiyonları** (`POST .../actions`): `client_action_id` istemci
  tarafından üretilir (UUID). Aynı `client_action_id` ile tekrar gönderilen
  istek **aynı sonucu** döner, ikinci bir `SwipeAction`/`ReplacementCandidate`
  ÜRETMEZ. Ağ hatası sonrası retry güvenlidir.
- **S3 upload event'leri** backend tarafında zaten idempotent (ETag bazlı
  kilit) — mobilin bir şey yapması gerekmez.
- **Tazelik değerlendirmesi** (`POST .../freshness-assessments`): opsiyonel
  `assessment_id` gönderilebilir; aynı ID tekrar gelirse olay tekrar
  yazılmaz (idempotent no-op, mevcut kayıt döner).

### 4.3 Tarih/saat biçimleri

| Alan tipi | Biçim | Örnek |
|---|---|---|
| Tarih (`*_date`, `*_until`) | `YYYY-MM-DD`, saatsiz | `2026-09-20` |
| Zaman damgası (`*_at`) | ISO-8601 UTC | `2026-09-11T15:30:00Z` |
| Yerel saat (bildirim tercihi) | `HH:mm` | `18:30` |

### 4.4 Sürüm/optimistic concurrency

`InventoryItem.version` her güncellemede artar. Mobil, kendi local
`InventoryItem`'ında bu alanı saklamalı; şimdilik backend `version`
uyuşmazlığını reddetmiyor (son yazan kazanır), ama alan gelecekte
optimistic-lock için kullanılabilir — mobil şimdiden saklarsa geriye dönük
uyumluluk sorunsuz olur.

---

## 5. Endpoint referansı

Base URL: `{ApiUrl}`. Tüm istekler `Authorization: Bearer {id_token}` ister.

### 5.1 Profil & bildirim tercihi

```
GET  /v1/users/me
PUT  /v1/users/me                              { display_name, fridge_id }
PUT  /v1/users/me/notification-preferences     { mode, digest_time?, quiet_hours_start?, quiet_hours_end?, timezone_id? }
```

`mode` ∈ `DAILY_DIGEST | CRITICAL_ONLY | OFF`.

### 5.2 Cihaz kaydı (push — gönderim sonraki fazda)

```
POST   /v1/devices                 { installation_id, push_token, platform? }  → 201
DELETE /v1/devices/{installation_id}                                            → 204
```

Mobil bu endpoint'i **şimdiden** çağırmalı (FCM token'ı kaydetmek için) —
sunucu tarafı push gönderimi eklendiğinde mobilde değişiklik gerekmeyecek.
`platform` varsayılan `"android"`.

### 5.3 Fotoğraf yükleme

```
POST /v1/uploads                        → 201
{ "upload_id", "object_key", "url", "fields": {...}, "status": "PENDING" }
```

`url` + `fields`: S3 presigned POST. Mobil `multipart/form-data` ile `fields`
içindeki tüm alanları **değiştirmeden** ekleyip dosyayı `file` alanıyla
POST eder — bu istek API'ye değil **doğrudan S3'e** gider, `Authorization`
header'ı GÖNDERİLMEZ (S3 imza kendi başına yetkilendirir).

Yükleme öncesi: uzun kenar ≤1024px, JPEG q80, EXIF/GPS temizle (SRS FR-CAP,
NFR-PRIV-002).

```
GET /v1/uploads/{upload_id}             → 200
{
  "upload_id", "status": "PENDING|PROCESSING|COMPLETED|FAILED",
  "observation_id": string|null,
  "items": [InventoryItem, ...],        // yalnızca COMPLETED'de dolu
  "source_image_url": string|null,      // kırpma için presigned GET, ~5dk geçerli
  "error": string|null
}
```

Polling: ~2 sn aralık, ~60 sn timeout (SRS §8.4 — WorkManager ile arka planda
sürdürülmeli, kullanıcı ekran değiştirebilmeli).

### 5.4 Envanter

```
GET    /v1/items                                    → { "items": [InventoryItem, ...] }
PATCH  /v1/items/{item_id}                          { name?, brand?, category?, subcategory?, package_state?, quantity?, state? } → InventoryItem
DELETE /v1/items/{item_id}                          → 204
```

`GET /v1/items` yalnızca `state=ACTIVE` kalemleri, etkin tazelik tarihine göre
artan sırada döner (backend GSI1 sıralaması — istemci tekrar sıralamamalı).

**`InventoryItem` şeması** (tüm okuma endpoint'lerinde aynı):

```json
{
  "item_id": "itm_...",
  "fridge_id": "ARC-FRIDGE-001",
  "name": "süt",
  "brand": "Sütaş",
  "raw_label": "Sütaş Günlük Süt 1L",
  "category": "dairy",
  "subcategory": "milk_fresh",
  "package_state": "unopened",
  "quantity": { "value": 1, "unit": "bottle" },
  "estimated_freshness_date": "2026-09-18",
  "predicted_fresh_until": "2026-09-18",
  "user_adjusted_fresh_until": null,
  "effective_fresh_until": "2026-09-18",
  "freshness_basis": "CATEGORY_HEURISTIC",
  "confidence": { "name": 0.92, "category": 0.96 },
  "needs_review": false,
  "state": "ACTIVE",
  "bounding_box": { "ymin": 120, "xmin": 60, "ymax": 640, "xmax": 340 },
  "last_reviewed_at": null,
  "next_review_at": null,
  "user_requested_review": false,
  "image_ref": null,
  "version": 1
}
```

> `estimated_freshness_date` ve `predicted_fresh_until` **aynı değeri** taşır
> (ikincisi mobil SRS adlandırmasıyla eşleşsin diye eklendi, birincisi geriye
> dönük uyumluluk için korunur). Yeni entegrasyonlarda `predicted_fresh_until`
> + `user_adjusted_fresh_until` + `effective_fresh_until` üçlüsünü kullanın.

### 5.5 Swipe aksiyonları

```
POST /v1/items/{item_id}/actions        → 201
{
  "client_action_id": "<uuid>",         // ZORUNLU, idempotency anahtarı
  "type": "CONSUMED" | "DISCARDED" | "REVIEWED",
  "occurred_at": "2026-09-11T15:30:00Z", // opsiyonel, yoksa sunucu zamanı
  "discard_reason": "OVERPURCHASED" | "NO_OPPORTUNITY_TO_CONSUME" |
                     "SPOILED_EARLIER_THAN_EXPECTED" | "IMPROPER_STORAGE" |
                     "WRONG_DETECTION" | "OTHER" | "PREFER_NOT_TO_SAY"
                     // yalnızca type=DISCARDED için anlamlı, opsiyonel
}
```

Yanıt:

```json
{
  "action": { "action_id", "client_action_id", "item_id", "type",
              "occurred_at", "previous_item_state", "discard_reason",
              "reverted_at", "replacement_candidate_id" },
  "candidate": ReplacementCandidate | null,   // CONSUMED/DISCARDED için dolu
  "item": InventoryItem                       // güncel durumuyla
}
```

`REVIEWED` tipi item durumunu DEĞİŞTİRMEZ, yalnız olay kaydı bırakır (kart
"kontrol edildi" işaretlenmiş olur, kuyruktan düşmez — asıl tazelik
güncellemesi §5.6'daki assessment endpoint'iyle yapılır).

**Geri alma** (BR-007, ~8 sn pencere UI'da yönetilir, backend süre sınırı
koymaz):

```
POST /v1/item-actions/{action_id}/undo   → 200
{ "action": {...., "reverted_at": "2026-09-11T15:30:08Z"} }
```

Item önceki duruma döner, varsa ilişkili `ReplacementCandidate` `REVERTED`
olur. İkinci kez undo çağrısı idempotent no-op'tur.

### 5.6 Tazelik değerlendirmesi

```
POST /v1/items/{item_id}/freshness-assessments   → 201
{
  "observed_state": "STILL_FRESH" | "BORDERLINE" | "SPOILED" | "UNSURE",  // ZORUNLU
  "user_estimated_days_remaining": 3,             // opsiyonel, >=0
  "user_estimated_fresh_until": "2026-09-20",     // opsiyonel
  "next_review_at": "2026-09-12T15:30:00Z",       // opsiyonel
  "reason": "LOOKS_FRESH" | "TEXTURE_CHANGED" | "SMELL_CHANGED" |
             "PACKAGE_DAMAGED" | "OPENED_TODAY" | "WRONG_DETECTION" |
             "OTHER" | "PREFER_NOT_TO_SAY"        // opsiyonel
}
```

Yanıt:

```json
{
  "assessment": { "assessment_id", "item_id", "assessed_at", "observed_state",
                   "user_estimated_days_remaining", "user_estimated_fresh_until",
                   "system_predicted_fresh_until_before", "next_review_at",
                   "reason", "rule_version" },
  "item": InventoryItem   // predicted_fresh_until DEĞİŞMEMİŞ, user_adjusted_fresh_until dolmuş olabilir
}
```

**Kritik davranış (BR-009):** `predicted_fresh_until` bu çağrıyla asla
değişmez. Yalnızca `user_estimated_fresh_until` verilirse
`user_adjusted_fresh_until` ve dolayısıyla `effective_fresh_until` güncellenir.
Hiçbir alan zorunlu değildir (`observed_state` hariç) — kullanıcı rastgele
cevap vermeye zorlanmamalı (SRS §16.3).

### 5.7 Kontrol kuyruğu

```
GET /v1/review-queue   → 200
{
  "queue": [
    { "item_id", "priority": 1, "reason": "USER_SCHEDULED"|"OVERDUE"|"CRITICAL"|"APPROACHING"|"NEEDS_REVIEW",
      "days_remaining": -2, "item": InventoryItem }
  ],
  "total_pending": 4
}
```

Sıralama backend'de BR-004'e göre yapılır (kullanıcının kontrol zamanı gelen
→ süresi geçen → kritik (0-2 gün) → yaklaşan (3-5 gün) → düşük güven/istek
üzerine); mobil bu sırayı **korumalı**, tekrar sıralamamalı. Kart deste
mantığı (10'lu gruplar, aynı oturumda tekrar göstermeme — BR-005) tamamen
istemci tarafı state'tir, backend'in bilgisi dışındadır.

### 5.8 Alışveriş listesi

```
GET    /v1/shopping-lists/current                                    → { "active": [...], "completed": [...] }
POST   /v1/shopping-lists/current/items      { name, category?, quantity?, note? }   → 201 ShoppingListItem
PATCH  /v1/shopping-lists/current/items/{id} { name?, category?, quantity?, state?, note? } → 200 ShoppingListItem
DELETE /v1/shopping-lists/current/items/{id}                          → 204
```

`ShoppingListItem`:

```json
{
  "shopping_item_id": "shop_...",
  "name": "domates",
  "state": "ACTIVE" | "COMPLETED" | "REMOVED",
  "category": "produce_vegetable" | null,
  "quantity": { "value": 3, "unit": "piece" } | null,
  "source_candidate_id": "cand_..." | null,
  "note": "..." | null,
  "created_at": "...", "updated_at": "..."
}
```

### 5.9 Yeniden alma önerileri (Replacement candidates)

```
GET  /v1/replacement-candidates?status=PENDING   → { "candidates": [...] }   // status opsiyonel, varsayılan PENDING
POST /v1/replacement-candidates/{id}/accept       → 201 { "shopping_item": ShoppingListItem }
POST /v1/replacement-candidates/{id}/dismiss      → 200 { "candidate_id", "status": "DISMISSED" }
```

`ReplacementCandidate.status` ∈ `PENDING | ACCEPTED | DISMISSED | REVERTED`.
Bir öneri kullanıcı onayı olmadan (accept çağrılmadan) aktif alışveriş
listesine **asla** eklenmez (BR-010) — bu kural backend'de zorlanır (409
`conflict` döner PENDING olmayan bir öneri kabul edilmeye çalışılırsa).

### 5.10 Tarifler

```
GET /v1/recipes/recommendations?allergens=yumurta,sut&diets=vegan&meal_type=ana_yemek&max_prep_minutes=20
→ 200
{
  "dataset_version": "recipes-2026-09-v1",
  "recommendations": [
    { "recipe_id", "title", "match_score": 0-100, "expiring_used_count",
      "missing_required": ["..."], "description", "meal_types": [...],
      "servings", "prep_minutes", "cook_minutes", "allergen_tags": [...],
      "diet_tags": [...] }
  ]
}
```

Tüm parametreler opsiyonel. `allergens`/`diets` virgülle ayrılmış liste.
Skor **deterministiktir** (BR-012) — generative AI kullanılmaz, sabit sürümlü
veri setinden (`src/core/recipes.json`) hesaplanır.

### 5.11 Reminder (bireysel hatırlatma, opt-in)

```
PUT    /v1/items/{item_id}/reminder    { scheduled_at, enabled? }   → 200 ItemReminder
DELETE /v1/items/{item_id}/reminder                                  → 204
```

Bu yalnızca **backend tarafı kaydı** tutar; gerçek bildirim gönderimi
sonraki fazdadır (§9). Mobil şimdilik kendi `WorkManager` reminder'ını da
paralel kurmalı.

---

## 6. Kotlin repository arayüzü eşlemesi

SRS §13.2'deki arayüzlerin cloud implementasyonları bu endpoint'lere şöyle
bağlanır:

| Kotlin arayüzü | Cloud implementasyonu → endpoint(ler) |
|---|---|
| `InventoryRepository` | `ApiInventoryRepository` → `GET/PATCH/DELETE /v1/items`, `GET /v1/uploads/{id}` |
| `SwipeActionRepository` | `ApiSwipeActionRepository` → `POST /v1/items/{id}/actions`, `POST /v1/item-actions/{id}/undo` |
| `FreshnessAssessmentRepository` | `ApiFreshnessAssessmentRepository` → `POST /v1/items/{id}/freshness-assessments` |
| `ShoppingRepository` | `ApiShoppingRepository` → `GET/POST/PATCH/DELETE /v1/shopping-lists/current/items`, `GET/POST /v1/replacement-candidates` |
| `RecipeRepository` | `RemoteRecipeRepository` → `GET /v1/recipes/recommendations` (yerel `JsonRecipeRepository` yerine; istenirse ikisi birlikte tutulup çevrimdışı fallback yapılabilir) |
| `UserPreferencesRepository` | Profil kısmı `ApiUserRepository` → `GET/PUT /v1/users/me`, `PUT /v1/users/me/notification-preferences`; local UI tercihleri (tema, grid/liste) yine `DataStore`'da kalır |
| `ReminderScheduler` | `CloudAwareReminderScheduler` → `PUT/DELETE /v1/items/{id}/reminder` + yerel `WorkManager` (push gelene kadar birincil mekanizma) |
| `ProductAnalyzer` | Doğrudan endpoint değil — `POST /v1/uploads` + presigned S3 + `GET /v1/uploads/{id}` polling üçlüsünün sarmalayıcısı |
| `SyncOutboxRepository` | `ApiSyncOutboxProcessor` → outbox'taki her olay tipini ilgili endpoint'e çevirir (bkz. §7) |

`AwsVisionProductAnalyzer` önerilen akış:

```kotlin
suspend fun analyze(imageUri: Uri): UploadResult {
    val presign = api.createUpload()                       // POST /v1/uploads
    s3Client.uploadMultipart(presign.url, presign.fields, imageFile)
    return pollUntilTerminal(presign.uploadId)              // GET /v1/uploads/{id}, ~2sn/60sn
}
```

---

## 7. Local-first senkronizasyon (outbox → endpoint eşlemesi)

SRS §12.17 `OutboxEvent.eventType` değerlerinin cloud karşılığı:

| `eventType` (öneri) | Endpoint | Not |
|---|---|---|
| `ITEM_CONSUMED` / `ITEM_DISCARDED` | `POST /v1/items/{id}/actions` | `client_action_id = eventId` — outbox zaten benzersiz kimlik taşıyorsa yeniden üretmeye gerek yok, doğrudan onu kullan |
| `ITEM_ACTION_REVERTED` | `POST /v1/item-actions/{actionId}/undo` | `actionId`, orijinal aksiyonun sunucu yanıtındaki `action_id` |
| `FRESHNESS_ASSESSED` | `POST /v1/items/{id}/freshness-assessments` | `assessment_id = eventId` |
| `SHOPPING_ITEM_ADDED/UPDATED/REMOVED` | `POST`/`PATCH`/`DELETE /v1/shopping-lists/current/items` | — |
| `CANDIDATE_ACCEPTED/DISMISSED` | `POST /v1/replacement-candidates/{id}/accept` \| `/dismiss` | — |
| `NOTIFICATION_PREFS_UPDATED` | `PUT /v1/users/me/notification-preferences` | Son yazan kazanır, çakışma yönetimi gerekmez |

`4xx` → kalıcı hata (`OutboxState.FAILED_PERMANENT`, tekrar denenmez, kullanıcıya
gösterilir). `5xx`/ağ hatası → `FAILED_RETRYABLE` (üstel geri çekilmeyle
tekrar dene). `409` özel durum: `profile_required` ise kullanıcıyı kayıt
akışına yönlendir (outbox'ı boşaltma, kayıt tamamlanınca yeniden dene).

---

## 8. Ürün görseli kırpma (bounding box)

Backend kırpma yapmaz; `bounding_box` (varsa) + `source_image_url` döner.
Web referans implementasyonu **CSS arka plan kırpması** kullanır (canvas/CORS
gerektirmez) — Kotlin tarafında en yakın karşılık:

```kotlin
fun cropBox(source: Bitmap, box: BoundingBox): Bitmap {
    val left = (box.xmin / 1000f * source.width).toInt()
    val top = (box.ymin / 1000f * source.height).toInt()
    val width = ((box.xmax - box.xmin) / 1000f * source.width).toInt()
    val height = ((box.ymax - box.ymin) / 1000f * source.height).toInt()
    return Bitmap.createBitmap(source, left, top, width, height)
}
```

`source_image_url` yalnızca ~5 dakika geçerlidir (`GET /v1/uploads/{id}`
her çağrıldığında yeniden üretilir) — kırpılmış sonucu kalıcı olarak
saklamak isterseniz indirip yerel dosyaya/`image_ref` alanına yazın; URL'yi
kalıcı referans olarak SAKLAMAYIN.

> Sonraki fazda kırpma buluta taşınacak (Lambda + Pillow + S3 `crops/` +
> kalıcı presigned URL) — o noktada mobil yalnızca hazır bir `crop_url`
> alanı kullanacak, bu bölümdeki istemci-taraflı kırpma kodu kaldırılabilir.
> Bu geçiş **API'de kırıcı değişiklik gerektirmeyecek** şekilde tasarlandı
> (yeni alan eklenir, mevcut alanlar kalır).

---

## 9. Bildirimler — mevcut durum ve mobil beklenti

- `POST /v1/devices` ile cihaz/push token kaydı **çalışır** ve saklanır.
- `PUT /v1/users/me/notification-preferences` ile tercih **çalışır** ve saklanır.
- Gerçek push **gönderimi** (FCM/SNS/AWS End User Messaging) **YOK**.
- **Mobil beklenti:** günlük özet bildirimi şimdilik yerel `WorkManager` ile
  üretilmeye devam etmeli (`GET /v1/review-queue` sonucuna göre — kuyruk
  boşsa bildirim yok, SRS FR-NOT-002). Cihaz kaydı yine de yapılmalı ki push
  gönderimi eklendiğinde ek bir mobil deploy gerekmesin.

---

## 10. Test/kabul kriterleri (entegrasyon için)

- [ ] PKCE akışı gerçek Cognito Hosted UI ile tamamlanıyor, `id_token` API
      isteklerinde kabul ediliyor.
- [ ] 404 `profile_not_found` → kayıt ekranı → `PUT /v1/users/me` → 201/200
      akışı çalışıyor; geçersiz fridge ID `400 invalid_fridge_id` ile
      düzgün gösteriliyor.
- [ ] Aynı buzdolabı ID'sine kayıtlı iki farklı hesap aynı envanteri görüyor
      (hane modeli doğrulaması).
- [ ] Fotoğraf yükleme → polling → envanterde ürün beliriyor; `bounding_box`
      varsa kırpılmış görsel gösteriliyor.
- [ ] Sağ/sol swipe `POST .../actions` çağırıyor, ~8 sn içinde undo
      çalışıyor, aynı `client_action_id` ile tekrar gönderim (network retry
      simülasyonu) ikinci bir öneri ÜRETMİYOR.
- [ ] Yukarı swipe değerlendirmesi `predicted_fresh_until`'i DEĞİŞTİRMİYOR,
      yalnız `user_adjusted_fresh_until`/`effective_fresh_until` güncelliyor.
- [ ] Kontrol kuyruğu sırası backend'den geldiği gibi korunuyor.
- [ ] Öneri kabul edilince alışveriş listesinde beliriyor; reddedilince
      düşüyor; swipe geri alınınca öneri `REVERTED` oluyor ve listede
      görünmüyor.
- [ ] Tarif önerileri alerjen filtresini güvenli biçimde uyguluyor (filtrelenen
      tarif hiç listelenmiyor, skorlanıp gösterilmiyor).
- [ ] Token süresi dolduğunda sessiz tazeleme çalışıyor; refresh de
      başarısızsa kullanıcı nazikçe yeniden girişe yönlendiriliyor.
- [ ] APK/AAB'de secret taraması temiz (SRS NFR-SEC-001, 20.5).

---

## 11. Bilinen sınırlamalar (bu fazda kapsam dışı)

- Gerçek push bildirim gönderimi (§9).
- Sunucu tarafı ürün görseli kırpma/kalıcı thumbnail (§8).
- Çoklu cihaz çakışma politikası (SRS §24.10) — şu an son yazan kazanır.
- Kullanıcı geri bildiriminin global raf ömrü kurallarına otomatik yansıması
  — BR-009 gereği bilinçli olarak yok; ayrı bir analiz/onay süreci gerekir.
