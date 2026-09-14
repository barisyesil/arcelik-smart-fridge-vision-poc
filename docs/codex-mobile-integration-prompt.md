# Codex Prompt — Mobil Cloud Entegrasyonu

Bu dosyanın içeriğini olduğu gibi Codex'e (Kotlin mobil repo'sunda çalışan
oturuma) yapıştırın. `docs/mobile-integration-plan.md` dosyasını da aynı
oturuma ekleyin/erişilebilir yapın — bu prompt ona ve backend repo'suna atıfta
bulunur. Backend repo'sundaki (bu repo) dosya yolları prompt içinde geçtiği
gibi verilmiştir; Codex bu dosyaları **kendisi okuyup** sözleşmeyi doğrulamalı.

---

```
Sen bu Android (Kotlin, Jetpack Compose) uygulamasını cloud backend'e
bağlayacaksın. Uygulama ŞU AN tamamen mock/prototip: gerçek kullanıcı girişi
YOK, gerçek backend bağlantısı YOK; ekranlar sabit/mock verilerle ve pakete
gömülü örnek görsellerle çalışıyor. Bu görevin iki yönü var:

  (A) Gerçek cloud'a bağla — Amazon Cognito ile giriş (sıfırdan) + tüm
      `/v1/*` endpoint'leri.
  (B) Mock iskelesini TEMİZLE — sahte veriler, gömülü örnek görseller ve
      yalnızca demo için var olan mock repository implementasyonları
      kaldırılsın; uygulama şişmeden, tek gerçek veri kaynağı cloud olacak
      şekilde sadeleşsin.

Sözleşme iki yerdedir ve ikisi de bağlayıcıdır; TAHMİN YÜRÜTME:
  1. Ekteki "Mobil ↔ Cloud Entegrasyon Planı" (mobile-integration-plan.md):
     auth akışı (Cognito Authorization Code + PKCE), buzdolabı/hane veri
     modeli, TÜM endpoint sözleşmeleri (miktar/birim/aralık semantiği dahil),
     Kotlin repository eşlemesi, outbox senkron kuralları, kabul kriterleri.
  2. Backend repo'sunun kaynak kodu — aşağıdaki "ÖNCE ANALİZ ET" bölümündeki
     dosyalar tek gerçek referanstır. Plan ile kod çelişirse KODU esas al ve
     bana bildir.

── ÖNCE ANALİZ ET (backend repo'sunu kendin oku, kopyala-yapıştır çözümleme) ──
Aşağıdaki dosyaları oku ve mobil eşlemesini bunlara dayandır:
  • Kimlik & altyapı: infra/stacks/fridge_stack.py
      - Cognito UserPool + "MobileClient" (public, generate_secret=False,
        callback_urls=["arcelikfridge://auth"], logout_urls=["arcelikfridge://signout"]).
      - API Gateway HTTP API + JWT authorizer; Lambda ortamı "AUTH_MODE": "jwt".
      - CfnOutput'lar: UserPoolId, UserPoolClientId (MOBİL client — WebTestClientId
        DEĞİL), CognitoDomain, ApiUrl, SeedFridgeIds. Deploy değerlerini bunlardan al.
  • Endpoint yönlendirme & davranış: src/handlers/inventory_api.py (ROUTES tablosu),
    src/handlers/presign.py (POST /v1/uploads), src/handlers/extractor.py (S3→Gemini).
  • Çıktı (DTO) SÖZLEŞMESİ — istemcinin alacağı JSON'ın birebir kaynağı:
    src/handlers/dto.py (item_to_json, shopping/candidate/assessment/reminder to_json).
  • Ürün/veri modeli & enum'lar: src/core/models.py, src/core/taxonomy.py
      - QUANTITY_UNITS (birim kapalı listesi), FoodCategory/subcategory, PackageState.
  • Çıkarım sözleşmesi (mobilin üzerinde değişiklik YAPMAYACAĞI üretim promptu):
    src/core/extraction.py (SYSTEM_PROMPT, PROMPT_VERSION, build_response_schema).
  • Kalıcılık / cloud veri noktaları: src/adapters/repository.py (DynamoDB tek tablo,
    FRIDGE#{id} partition), src/core/inventory.py (anahtar üretimi). Mobil DynamoDB'ye
    doğrudan erişmez — ama hangi verinin buzdolabı (hane) bazında paylaşıldığını,
    hangisinin (profil/cihaz/tercih) kullanıcıya özel olduğunu buradan doğrula.
  • PKCE REFERANS implementasyonu (aynı akışın çalışan hâli): web/src/api/auth.ts
    (authorize/token/refresh URL inşası, S256), web/src/hooks/useAuth.ts (durum,
    callback işleme). Kotlin'de bunu AppAuth-Android ile birebir kur.

── MEVCUT MOBİL KODU KEŞFET ──
  1. Hangi repository arayüzleri (SRS: InventoryRepository, SwipeActionRepository,
     FreshnessAssessmentRepository, ShoppingRepository, RecipeRepository,
     UserPreferencesRepository, ReminderScheduler, ProductAnalyzer,
     SyncOutboxRepository) tanımlı; her biri için MOCK/FAKE implementasyon
     hangileri; DI (Hilt) modülleri mock'ları nerede bağlıyor.
  2. Pakete gömülü örnek/mock görseller (drawable/assets/res içindeki demo
     fotoğrafları), sahte seed verileri, "FakeX"/"MockX"/"SampleX"/"demo"
     isimli sağlayıcılar, hardcoded örnek envanter/tarif/alışveriş listeleri
     — hepsini envanterle.
  3. Gerçek giriş var mı? (Muhtemelen yok.) Auth/oturum durumu nasıl temsil
     ediliyor, uygulama açılışında ilk hangi ekran geliyor.

── (A) CLOUD ENTEGRASYONU: TEMEL İLKELER (plandaki bölüme atıfla uygula) ──
  • Giriş SIFIRDAN eklenecek: Authorization Code + PKCE, PUBLIC client (secret
    YOK). AppAuth-Android kullan; elle OAuth yazma. (plan §2)
  • Kimlik yalnızca id_token'dan gelir; hiçbir header'a kullanıcı kimliği elle
    yazılmaz. API çağrılarında `Authorization: Bearer {id_token}` (access_token
    DEĞİL). (plan §2.3)
  • Token'lar EncryptedSharedPreferences/Keystore'da; token/presigned URL/kişisel
    veri hiçbir yerde (log, crash, analytics) geçmez. 401'de bir kez refresh,
    olmazsa oturumu kapat. (plan §2.4)
  • İlk açılışta GET /v1/users/me; 404 profile_not_found → kayıt ekranı
    (Ad-Soyad + SeedFridgeIds'ten bir buzdolabı ID) → PUT /v1/users/me. Herhangi
    bir istekte 409 profile_required gelirse aynı kayıt akışına yönlendir.
    (plan §3)
  • Hane modeli: veri buzdolabı bazında paylaşılır; istemci `fridge_id`'yi
    isteklere GÖNDERMEZ (yalnız UI'da gösterir), kimlik JWT+profil ile backend'de
    çözülür. (plan §1, §3)
  • Fotoğraf: POST /v1/uploads → presigned S3'e DOĞRUDAN multipart upload
    (Authorization header'sız) → GET /v1/uploads/{id} polling (~2sn/60sn,
    WorkManager ile arka planda). (plan §5.3, §6)
  • KONTROL EKRANI + ONAY — YENİ, ZORUNLU AKIŞ (plan §5.3.1–5.3.2): Fotoğraf
    ARTIK otomatik EKLEMEZ. Polling sonucu DRAFT ürünlerdir (state="DRAFT") ve
    `GET /v1/items`'te GÖRÜNMEZ. Kontrol ekranında kullanıcı bunları (kırpılmış
    önizlemeyle) görür, düzenler, seçer. Onayda: her onaylanan ürün için crop'u
    `POST /v1/uploads/{id}/crops` ile presigned S3'e yükle, dönen object_key'i
    `POST /v1/uploads/{id}/confirm` gövdesinde `image_key` olarak ver.
    Confirm'de OLMAYAN draft'lar SİLİNİR. Onaylananlar ACTIVE olur, envanterde
    belirir ve okuma yanıtlarında görüntüleme için kalıcı `image_url` taşır.
    Kullanıcı onaysız çıkarsa ürün EKLENMEZ (draft TTL ile silinir). Mevcut
    "fotoğraf çekince kaydet" ekran semantiğini bu akışa göre DÜZELT.
  • Ürün fotoğrafı görüntüleme: envanterde ürünü `image_url` (presigned GET,
    ~5 dk) ile göster; URL'yi kalıcı saklama, gerektiğinde kalemi yeniden oku.
    `image_ref` kalıcı S3 anahtarıdır; null ise ürünün kalıcı fotoğrafı yok.
  • Miktar/birim/sayım — YENİ SÖZLEŞME (plan §5.4.1): bir ürün grubu tek
    kalemdir; `quantity.value` kesin sayı ya da aralığın alt sınırı,
    `quantity.value_max` (null=kesin) üst sınırı; `unit` kapalı listeden
    (piece/pack/box/bottle/bunch/bag/carton/gram/milliliter). UI adedi "8–10"
    gibi aralık ya da "10" gibi tek sayı + birim Türkçesiyle gösterir; birim
    uydurma. Referans biçimleme: web/src/lib/labels.ts (formatQuantity).
  • bounding_box artık ürün GRUBU başına; kırpma o grubu tek görsele kırpar
    (istemci tarafı, 0-1000 ölçeği × bitmap boyutu). source_image_url ~5 dk
    geçerli; kalıcı referans olarak SAKLAMA. (plan §5.4, §8)
  • Swipe aksiyonları idempotent client_action_id (UUID) ile; ~8 sn undo
    penceresi UI'da yönetilir. (plan §4.2, §5.5)
  • predicted_fresh_until hiçbir mobil yolda ezilmez; kullanıcı düzeltmesi ayrı
    (user_adjusted_fresh_until/effective_fresh_until). Kontrol kuyruğu sırası
    backend'den geldiği gibi korunur. Replacement candidate accept edilmeden
    listeye girmez. Tarifler client-side AI ile üretilmez. (plan §5.6, §5.7,
    §5.9, §5.10)
  • Push GÖNDERİMİ backend'de yok (yalnız cihaz kaydı/tercih). Mevcut yerel
    WorkManager bildirim mekanizmasını koru; cihaz kaydını (POST /v1/devices)
    ek olarak yap. (plan §5.2, §9)

── (B) MOCK TEMİZLİĞİ: TEMİZ, ŞİŞMEYEN YAPI ──
Amaç: cloud tek gerçek veri kaynağı olduktan sonra prototip iskelesi ölü
ağırlık bırakmasın.
  • Sahte veri sağlayıcıları ve mock repository implementasyonlarını KALDIR:
    ekranlara demo envanter/tarif/alışveriş/kuyruk üreten "Fake/Mock/Sample/demo"
    sınıfları, hardcoded listeler, in-memory seed'ler. Yerlerine cloud
    (`Api*Repository`) implementasyonlarını BİRİNCİL ve tek bağlanan olarak koy;
    Hilt modüllerinde mock binding'leri sil.
  • Pakete gömülü örnek/mock GÖRSELLERİ kaldır (drawable/assets/res'teki demo
    fotoğrafları). Gerçek görseller kullanıcının çektiği + S3'ten gelen
    presigned URL'lerdir. Yalnızca gerçekten gereken UI ikon/illüstrasyonlarını
    bırak; ürün örneği fotoğraflarını sil.
  • Kullanılmayan hâle gelen kod/bağımlılık/string/kaynağı da temizle (dead
    code, artık çağrılmayan mock DI modülleri, gereksiz test fixture görselleri).
    Amaç APK/AAB boyutunu ve karmaşayı düşürmek.
  • DİKKAT — neyi SİLME: gerçek offline/senkron ALTYAPISI mock değildir. Room
    cache, DataStore (tema/grid gibi yerel UI tercihleri), WorkManager, offline
    outbox MEKANİZMASI korunur; ama bunlar artık SAHTE değil GERÇEK cloud
    verisini cache'ler / gerçek olayları outbox'tan ilgili endpoint'e taşır
    (plan §7). Yani "mock veriyi" sil, "senkron mekanizmasını" tut. Bir Room/
    outbox parçası yalnızca mock'u beslemek için varsa ve cloud'da karşılığı
    yoksa, onu da kaldır. Emin olamadığın bir silme kararında DURUP SOR.
  • Repository ARAYÜZ sözleşmelerini kırma; yeni alan (ör. quantity.value_max)
    gerekiyorsa arayüzü/DTO'yu genişlet, yerine yenisini yazma (NFR-MNT-003).

── DEPLOY DEĞERLERİ ──
ApiUrl, UserPoolId, UserPoolClientId (MOBİL), CognitoDomain, SeedFridgeIds'i
nereden okuyacağını belirle (BuildConfig/gradle.properties/config dosyası).
Değerler sende yoksa placeholder bırak ve hangi değerlere ihtiyacın olduğunu
AÇIKÇA listele; uydurma. Callback şeması arcelikfridge://auth — farklı şema
istenirse önce infra'da (fridge_stack.py MobileClient) güncellenip yeniden
deploy edilmeli, yoksa Cognito redirect_mismatch döner.

── ÇALIŞMA TARZI ──
  • İşi küçük, gözden geçirilebilir adımlara böl. Önerilen sıra:
    1) Cognito PKCE giriş + token saklama + oturum durumu (ilk ekran akışı).
    2) Profil/kayıt (users/me 404→kayıt→PUT) + hane modeli.
    3) Mock envanter kaynağını cloud ile DEĞİŞTİR + upload/polling; aynı adımda
       o ekranın mock verisini/görsellerini kaldır.
    4) Swipe + undo (idempotency), 5) freshness-assessment, 6) review-queue,
    7) shopping + candidates, 8) recipes, 9) devices/prefs.
    Her adımda: ilgili mock'u kaldır → cloud'u bağla → derle → (varsa) test.
  • Ağ katmanını test edilebilir tut (arayüz + implementasyon ayrımı); mevcut
    test altyapısına (MockWebServer, Hilt test modülleri) uy. NOT: test amaçlı
    mock'lar (MockWebServer vb.) KALIR — kaldırılan yalnızca UYGULAMA kodundaki
    demo/seed mock'larıdır.
  • Belirsiz noktada (bir ekranın hangi repo'yu çağıracağı, bir mock'un gerçek
    karşılığı olup olmadığı) plan/koda bak; yine yoksa DURUP SOR, uydurma.
  • Sonunda RAPOR ver: (a) değişen/eklenen/SİLİNEN dosyalar (kaldırılan mock
    sınıfları ve görseller ayrı listelensin, tahmini boyut kazanımıyla), (b)
    eklenen bağımlılıklar (AppAuth vb.), (c) hâlâ elle girilmesi gereken config
    değerleri, (d) plandaki "Test/kabul kriterleri"nden hangileri karşılandı,
    (e) silme kararı verirken emin olamayıp bıraktığın/soru sorduğun noktalar.

Şimdi önce backend dosyalarını ve mobile-integration-plan.md'yi oku, mevcut
mobil koddaki mock envanterini çıkar, sonra hem cloud entegrasyonunu hem mock
temizliğini kapsayan bir uygulama planı öner — kod yazmadan önce onayımı bekle.
```
