/**
 * Sunum katmanı çevirisi. API kontratı `src/core/taxonomy.py`'deki İngilizce
 * kapalı enum anahtarlarını taşır; bunlar değişmez. Burada sadece kullanıcıya
 * gösterilen metni Türkçeleştiriyoruz. Bilinmeyen bir anahtar gelirse ham
 * değeri gösteririz, "undefined" ile çökme olmaz.
 */

export const CATEGORY_LABELS: Record<string, string> = {
  dairy: "Süt Ürünleri",
  meat_poultry: "Et ve Tavuk",
  deli: "Şarküteri",
  fish_seafood: "Deniz Ürünleri",
  egg: "Yumurta",
  produce_vegetable: "Sebze",
  produce_fruit: "Meyve",
  bakery: "Fırın Ürünleri",
  prepared_leftover: "Hazır / Artık Yemek",
  beverage: "İçecek",
  condiment_sauce: "Sos ve Baharat",
  preserves_pickles: "Konserve ve Turşu",
  pantry_dry: "Kuru Gıda",
  frozen: "Donuk Gıda",
  other: "Diğer",
};

export const SUBCATEGORY_LABELS: Record<string, string> = {
  // dairy
  milk_uht: "Uzun Ömürlü Süt",
  milk_fresh: "Taze Süt",
  yogurt: "Yoğurt",
  cheese_hard: "Sert Peynir",
  cheese_soft: "Yumuşak Peynir",
  ayran: "Ayran",
  kefir: "Kefir",
  butter: "Tereyağı",
  cream: "Krema / Kaymak",
  other_dairy: "Diğer Süt Ürünü",
  // meat_poultry
  ground_meat: "Kıyma",
  cubed_meat: "Kuşbaşı",
  steak_chop: "Biftek / Pirzola",
  chicken: "Tavuk Eti",
  turkey: "Hindi Eti",
  offal: "Sakatat",
  cooked_meat: "Pişmiş Et",
  other_meat: "Diğer Et",
  // deli
  sucuk: "Sucuk",
  salami: "Salam",
  sausage: "Sosis",
  pastirma: "Pastırma",
  ham: "Jambon",
  kavurma: "Kavurma",
  pate: "Pate",
  other_deli: "Diğer Şarküteri",
  // fish_seafood
  fish: "Balık",
  shrimp: "Karides",
  mussel: "Midye",
  squid: "Kalamar",
  canned_fish: "Konserve Balık",
  other_seafood: "Diğer Deniz Ürünü",
  // egg
  shell_egg: "Tavuk Yumurtası",
  quail_egg: "Bıldırcın Yumurtası",
  boiled_egg: "Haşlanmış Yumurta",
  // produce_vegetable
  tomato: "Domates",
  cucumber: "Salatalık",
  pepper: "Biber",
  eggplant: "Patlıcan",
  zucchini: "Kabak",
  leafy: "Marul / Yeşillik",
  onion: "Soğan",
  garlic: "Sarımsak",
  potato: "Patates",
  carrot: "Havuç",
  mushroom: "Mantar",
  brassica: "Brokoli / Karnabahar",
  bean_pea: "Yeşil Fasulye / Bezelye",
  fresh_herb: "Taze Ot",
  other_vegetable: "Diğer Sebze",
  // produce_fruit
  apple: "Elma",
  pear: "Armut",
  banana: "Muz",
  citrus: "Portakal / Mandalina",
  lemon: "Limon",
  strawberry: "Çilek",
  berry: "Yaban Mersini / Ahududu",
  grape: "Üzüm",
  melon: "Karpuz / Kavun",
  stone_fruit: "Şeftali / Kayısı",
  avocado: "Avokado",
  other_fruit: "Diğer Meyve",
  // bakery
  bread: "Ekmek",
  pastry: "Hamur İşi",
  cake: "Kek / Pasta",
  // prepared_leftover
  cooked_meat_dish: "Pişmiş Et Yemeği",
  cooked_vegetable_dish: "Pişmiş Sebze Yemeği",
  soup: "Çorba",
  rice_pasta: "Pilav / Makarna",
  dressed_salad: "Sos Gezdirilmiş Salata",
  // beverage
  water: "Su",
  fresh_juice: "Taze Sıkılmış Meyve Suyu",
  packaged_juice: "Ambalajlı Meyve Suyu",
  soda: "Gazlı İçecek",
  iced_tea: "Soğuk Çay",
  energy_drink: "Enerji İçeceği",
  herbal_tea: "Bitki Çayı",
  alcohol: "Alkollü İçecek",
  other_beverage: "Diğer İçecek",
  // condiment_sauce
  ketchup: "Ketçap",
  mayo: "Mayonez",
  mustard: "Hardal",
  tomato_paste: "Salça",
  vinegar: "Sirke",
  oil: "Yağ",
  dressing: "Salata Sosu",
  spice: "Baharat",
  other_sauce: "Diğer Sos",
  // preserves_pickles
  pickle: "Turşu",
  olive: "Zeytin",
  canned_vegetable: "Konserve Sebze",
  canned_fruit: "Konserve Meyve",
  jam: "Reçel / Marmelat",
  honey: "Bal",
  other_preserve: "Diğer Konserve",
  // pantry_dry
  flour_grain: "Un / Tahıl",
  dry_pasta_rice: "Kuru Makarna / Pirinç",
  dry_legume: "Kuru Bakliyat",
  nuts_seeds: "Kuruyemiş",
  // frozen
  frozen_vegetable: "Donuk Sebze",
  frozen_meat: "Donuk Et",
  frozen_potato: "Donuk Patates",
  frozen_pastry: "Donuk Hamur İşi",
  frozen_fish: "Donuk Balık",
  frozen_ready_meal: "Donuk Hazır Yemek",
  ice_cream: "Dondurma",
  other_frozen: "Diğer Donuk Ürün",
  // other
  unknown_food: "Tanımlanamayan Ürün",
};

export const PACKAGE_STATE_LABELS: Record<string, string> = {
  unopened: "Kapalı",
  opened: "Açık",
  unknown: "Belirsiz",
};

export const UPLOAD_STATUS_LABELS: Record<string, string> = {
  PENDING: "Bekliyor",
  PROCESSING: "İşleniyor",
  COMPLETED: "Tamamlandı",
  FAILED: "Başarısız",
};

export const QUANTITY_UNIT_LABELS: Record<string, string> = {
  piece: "adet",
  pack: "paket",
  bottle: "şişe",
  gram: "gram",
  milliliter: "ml",
};

export const REVIEW_REASON_LABELS: Record<string, string> = {
  USER_SCHEDULED: "Kontrol zamanı geldi",
  OVERDUE: "Süresi geçti",
  CRITICAL: "Kritik (0-2 gün)",
  APPROACHING: "Yaklaşıyor (3-5 gün)",
  NEEDS_REVIEW: "Doğrulama gerekiyor",
};

export const NOTIFICATION_MODE_LABELS: Record<string, string> = {
  DAILY_DIGEST: "Günlük özet",
  CRITICAL_ONLY: "Yalnız kritik",
  OFF: "Kapalı",
};

function label(map: Record<string, string>, key: string | null | undefined): string {
  if (!key) return "—";
  return map[key] ?? key;
}

export const categoryLabel = (key: string | null | undefined) => label(CATEGORY_LABELS, key);
export const subcategoryLabel = (key: string | null | undefined) => label(SUBCATEGORY_LABELS, key);
export const packageStateLabel = (key: string | null | undefined) =>
  label(PACKAGE_STATE_LABELS, key);
export const uploadStatusLabel = (key: string | null | undefined) =>
  label(UPLOAD_STATUS_LABELS, key);
export const quantityUnitLabel = (key: string | null | undefined) =>
  label(QUANTITY_UNIT_LABELS, key);
export const reviewReasonLabel = (key: string | null | undefined) =>
  label(REVIEW_REASON_LABELS, key);
export const notificationModeLabel = (key: string | null | undefined) =>
  label(NOTIFICATION_MODE_LABELS, key);
