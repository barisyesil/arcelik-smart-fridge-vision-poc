# Codex Prompt — Mobil Cloud Entegrasyonu

Bu dosyanın içeriğini olduğu gibi Codex'e (Kotlin mobil repo'sunda çalışan
oturuma) yapıştırın. `docs/mobile-integration-plan.md` dosyasını da aynı
oturuma ekleyin/erişilebilir yapın — bu prompt ona atıfta bulunur.

---

```
Sen bu Android (Kotlin, Jetpack Compose) uygulamasının local-first/mock
prototipini, ekteki "Mobil ↔ Cloud Entegrasyon Planı" belgesinde (mobile-
integration-plan.md) tanımlanan AWS backend'ine bağlayacaksın.

ÖNCE YAP:
1. mobile-integration-plan.md dosyasını baştan sona oku. Orada kimlik
   doğrulama akışı (Cognito Authorization Code + PKCE), buzdolabı/hane veri
   modeli, tüm endpoint sözleşmeleri, Kotlin repository eşlemesi, outbox
   senkron kuralları ve kabul kriterleri var — bunlar bu görevin
   sözleşmesidir, tahmin yürütme.
2. Mevcut Kotlin kod tabanını keşfet: hangi repository arayüzleri (SRS'teki
   InventoryRepository, SwipeActionRepository, FreshnessAssessmentRepository,
   ShoppingRepository, RecipeRepository, UserPreferencesRepository,
   ReminderScheduler, ProductAnalyzer, SyncOutboxRepository) zaten tanımlı,
   hangi mock/local implementasyonlar var, DI (Hilt) modülleri nasıl kurulu.
3. Deploy'a özel değerleri (ApiUrl, UserPoolId, UserPoolClientId,
   CognitoDomain, SeedFridgeIds) nereden okuyacağını belirle — muhtemelen
   BuildConfig/gradle.properties veya bir config dosyası. Bu değerler sende
   yoksa placeholder bırak ve bana hangi değerlere ihtiyacın olduğunu
   açıkça listele; uydurma.

TEMEL İLKELER (planın hangi bölümüne dayandığını referans vererek uygula):
- Kimlik doğrulama Authorization Code + PKCE, PUBLIC client (secret YOK).
  AppAuth-Android kullanman önerilir, sıfırdan OAuth yazma.
- Kimlik yalnızca id_token'dan gelir; hiçbir header'a kullanıcı kimliği
  elle yazılmaz.
- Token'lar EncryptedSharedPreferences/Keystore'da tutulur; hiçbir yerde
  (log, crash report, analytics) token/presigned URL/kişisel veri geçmez.
- İlk girişte GET /v1/users/me 404 dönerse kayıt ekranı (Ad-Soyad + buzdolabı
  ID'si) göster, PUT /v1/users/me ile tamamla; 409 profile_required başka
  bir isteğe denk gelirse aynı akışa yönlendir.
- Swipe aksiyonları (tükettim/attım/kontrol) idempotent client_action_id
  ile gönderilir; ~8 sn geri alma penceresi UI'da yönetilir.
- Sistem tahmini (predicted_fresh_until) hiçbir mobil kod yolunda ezilmez;
  kullanıcı düzeltmesi ayrı alanda (user_adjusted_fresh_until) tutulur.
- Kontrol kuyruğu sırası backend'den geldiği gibi korunur, istemci tekrar
  sıralamaz.
- Bir replacement candidate kullanıcı onayı (accept çağrısı) olmadan aktif
  alışveriş listesine asla eklenmez.
- Tarif önerileri client-side AI ile üretilmez; yalnızca backend'in
  döndürdüğü liste gösterilir.
- Mevcut local-first mimari (Room, DataStore, WorkManager, offline outbox)
  KALDIRILMAZ — cloud implementasyonlar aynı repository arayüzlerinin YENİ
  bir implementasyonu olarak eklenir (SRS'teki "Api*Repository" adlandırma
  kalıbı), böylece local/mock ve cloud implementasyonlar birbirinin yerine
  geçebilir kalır (NFR-MNT-003). Var olan arayüz sözleşmelerini KIRMA; yeni
  alan gerekiyorsa arayüzü genişlet, yerine yenisini yazma.
- Push bildirim GÖNDERİMİ backend'de henüz yok (yalnızca cihaz kaydı/tercih
  var) — mevcut yerel WorkManager bildirim mekanizmasını koru, cihaz kaydını
  ek olarak yap.

ÇALIŞMA TARZI:
- İşi küçük, gözden geçirilebilir adımlara böl (örn. önce auth, sonra
  profil/kayıt, sonra envanter+upload, sonra swipe+undo, sonra assessment,
  sonra review-queue, sonra shopping+candidates, sonra recipes, sonra
  devices/prefs). Her adımdan sonra derle ve (varsa) ilgili testleri çalıştır.
- Ağ katmanını test edilebilir tut (arayüz + gerçek/mock implementasyon
  ayrımı) — mevcut test altyapısına (varsa MockWebServer, Hilt test modülleri)
  uy.
- Belirsiz bir noktada (örn. bir ekranın hangi repository'yi çağıracağı,
  bir UI akışının tam davranışı) plan belgesinde yanıt yoksa DURUP SOR;
  uydurma veya sessizce farklı bir davranış seçme.
- Sonunda: hangi dosyaların değiştiğini, hangi yeni bağımlılıkların
  eklendiğini (örn. AppAuth, bir HTTP client), hangi config değerlerinin
  (ApiUrl vb.) hâlâ elle girilmesi gerektiğini ve plan belgesindeki "Test/
  kabul kriterleri" listesinden hangilerinin karşılandığını özetleyen bir
  rapor ver.

Şimdi mobile-integration-plan.md'yi oku ve bir uygulama planı öner — kod
yazmadan önce onayımı bekle.
```
