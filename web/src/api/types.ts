/**
 * API kontratı v1'in TypeScript karşılığı. Alan adı/tipi değişecekse önce
 * backend tarafında (`src/handlers/dto.py`, `src/core/models.py`), sonra
 * burada değişir.
 */

export type UploadStatusValue = "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";

export type FreshnessBasis = "CATEGORY_HEURISTIC" | "USER_PROVIDED";

export type PackageState = "unopened" | "opened" | "unknown";

export type ItemState = "DRAFT" | "ACTIVE" | "CONSUMED" | "DISCARDED";

export type QuantityUnit =
  | "piece"
  | "pack"
  | "box"
  | "bottle"
  | "bunch"
  | "bag"
  | "carton"
  | "gram"
  | "milliliter";

export interface Quantity {
  value: number;
  unit: QuantityUnit;
  /** Tahmini aralığın üst sınırı; kesin sayıda null/yok. `value` alt sınırdır. */
  value_max?: number | null;
}

export interface FieldConfidence {
  name: number;
  category: number;
}

/**
 * Ürünün kaynak fotoğraftaki konumu. Gemini konvansiyonu: `[ymin, xmin, ymax,
 * xmax]`, 0-1000 aralığına normalize. Arayüz bu oranları kaynak görselin gerçek
 * piksel boyutuyla çarpıp ürünü ayrı bir görsele kırpar. Kutu yoksa `null`.
 */
export interface BoundingBox {
  ymin: number;
  xmin: number;
  ymax: number;
  xmax: number;
}

export interface InventoryItemDto {
  item_id: string;
  fridge_id: string;
  name: string;
  brand: string | null;
  raw_label: string | null;
  category: string;
  subcategory: string | null;
  package_state: PackageState;
  quantity: Quantity;
  estimated_freshness_date: string;
  /** Sistem tahmini — kullanıcı geri bildirimi bunu ASLA ezmez (BR-009). */
  predicted_fresh_until: string;
  /** Kullanıcının yukarı-swipe değerlendirmesinden türeyen tarih, yoksa `null`. */
  user_adjusted_fresh_until: string | null;
  /** Kontrol sıralamasında kullanılan tarih: kullanıcı düzeltmesi varsa o, yoksa sistem tahmini. */
  effective_fresh_until: string;
  freshness_basis: FreshnessBasis;
  confidence: FieldConfidence | null;
  needs_review: boolean;
  state: ItemState;
  bounding_box: BoundingBox | null;
  last_reviewed_at: string | null;
  next_review_at: string | null;
  user_requested_review: boolean;
  /** Kalemin kalıcı crop'unun S3 anahtarı (onayda yazılır); yoksa `null`. */
  image_ref: string | null;
  /** `image_ref` varsa görüntüleme için kısa ömürlü presigned GET; kalıcı saklama. */
  image_url?: string | null;
  version: number;
}

export interface CreateUploadResponse {
  upload_id: string;
  object_key: string;
  url: string;
  fields: Record<string, string>;
  status: UploadStatusValue;
}

export interface UploadStatusResponse {
  upload_id: string;
  status: UploadStatusValue;
  observation_id: string | null;
  items: InventoryItemDto[];
  /**
   * İşlem tamamlandığında ve kırpılacak en az bir kutu varsa, kaynak
   * fotoğrafın kısa ömürlü presigned GET URL'si. Arayüz ürünleri bundan
   * kırpar. Kutu yoksa veya URL üretilemediyse `null`.
   */
  source_image_url: string | null;
  error: string | null;
  /**
   * Extractor'ın ölçtüğü aşama süreleri (ms): `queue_ms` (fotoğraf S3'e indi →
   * Lambda başlangıcı), `s3_fetch_ms`, `gemini_ms`, `parse_build_ms`. Darboğaz
   * analizi için; yalnızca COMPLETED'de dolu.
   */
  timings?: Record<string, number> | null;
}

export interface CreateCropUploadResponse {
  crop_id: string;
  object_key: string;
  url: string;
  fields: Record<string, string>;
}

/** Onayda tek bir DRAFT ürün için karar: item_id + opsiyonel crop anahtarı + düzenlemeler. */
export interface ConfirmItem {
  item_id: string;
  image_key?: string;
  name?: string;
  brand?: string;
  category?: string;
  subcategory?: string;
  package_state?: PackageState;
  quantity?: Quantity;
}

export interface ConfirmUploadResponse {
  items: InventoryItemDto[];
}

export interface ItemListResponse {
  items: InventoryItemDto[];
}

/** PATCH /v1/items/{id} gövdesi — sadece bu alanlar kabul edilir. */
export interface ItemPatch {
  name?: string;
  brand?: string;
  category?: string;
  subcategory?: string;
  package_state?: PackageState;
  quantity?: Quantity;
  state?: ItemState;
}

export interface ApiError {
  error: string;
  detail?: string;
}

// --- Profil & bildirim tercihleri ---

export type NotificationMode = "DAILY_DIGEST" | "CRITICAL_ONLY" | "OFF";

export interface NotificationPreferencesDto {
  mode: NotificationMode;
  digest_time: string; // "HH:mm"
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  timezone_id: string;
}

export interface UserProfileDto {
  user_id: string;
  fridge_id: string;
  display_name: string;
  created_at: string;
  updated_at: string;
  notification_preferences: NotificationPreferencesDto;
}

export interface RegisterProfileRequest {
  display_name: string;
  fridge_id: string;
}

// --- Swipe aksiyonları ---

export type SwipeActionType = "CONSUMED" | "DISCARDED" | "REVIEWED";

export type DiscardReason =
  | "OVERPURCHASED"
  | "NO_OPPORTUNITY_TO_CONSUME"
  | "SPOILED_EARLIER_THAN_EXPECTED"
  | "IMPROPER_STORAGE"
  | "WRONG_DETECTION"
  | "OTHER"
  | "PREFER_NOT_TO_SAY";

export interface SwipeActionRequest {
  client_action_id: string;
  type: SwipeActionType;
  occurred_at?: string;
  discard_reason?: DiscardReason;
}

export interface SwipeActionDto {
  action_id: string;
  client_action_id: string;
  item_id: string;
  type: SwipeActionType;
  occurred_at: string;
  previous_item_state: ItemState;
  discard_reason: DiscardReason | null;
  reverted_at: string | null;
  replacement_candidate_id: string | null;
}

export type ReplacementCandidateStatus = "PENDING" | "ACCEPTED" | "DISMISSED" | "REVERTED";

export interface ReplacementCandidateDto {
  candidate_id: string;
  source_item_id: string;
  source_action_id: string;
  name: string;
  category: string;
  reason: "CONSUMED" | "DISCARDED";
  status: ReplacementCandidateStatus;
  suggested_quantity: Quantity | null;
  created_at: string;
}

export interface SwipeActionResponse {
  action: SwipeActionDto;
  candidate: ReplacementCandidateDto | null;
  item: InventoryItemDto;
}

export interface UndoActionResponse {
  action: SwipeActionDto;
}

// --- Tazelik değerlendirmesi ---

export type ObservedFreshnessState = "STILL_FRESH" | "BORDERLINE" | "SPOILED" | "UNSURE";

export type FreshnessAssessmentReason =
  | "LOOKS_FRESH"
  | "TEXTURE_CHANGED"
  | "SMELL_CHANGED"
  | "PACKAGE_DAMAGED"
  | "OPENED_TODAY"
  | "WRONG_DETECTION"
  | "OTHER"
  | "PREFER_NOT_TO_SAY";

export interface FreshnessAssessmentRequest {
  observed_state: ObservedFreshnessState;
  user_estimated_days_remaining?: number;
  user_estimated_fresh_until?: string;
  next_review_at?: string;
  reason?: FreshnessAssessmentReason;
}

export interface FreshnessAssessmentDto {
  assessment_id: string;
  item_id: string;
  assessed_at: string;
  observed_state: ObservedFreshnessState;
  user_estimated_days_remaining: number | null;
  user_estimated_fresh_until: string | null;
  system_predicted_fresh_until_before: string;
  next_review_at: string | null;
  reason: FreshnessAssessmentReason | null;
  rule_version: string;
}

export interface AssessmentResponse {
  assessment: FreshnessAssessmentDto;
  item: InventoryItemDto;
}

// --- Kontrol kuyruğu ---

export type ReviewReason = "USER_SCHEDULED" | "OVERDUE" | "CRITICAL" | "APPROACHING" | "NEEDS_REVIEW";

export interface ReviewQueueEntryDto {
  item_id: string;
  priority: number;
  reason: ReviewReason;
  days_remaining: number;
  item: InventoryItemDto;
}

export interface ReviewQueueResponse {
  queue: ReviewQueueEntryDto[];
  total_pending: number;
}

// --- Alışveriş listesi ---

export type ShoppingItemState = "ACTIVE" | "COMPLETED" | "REMOVED";

export interface ShoppingListItemDto {
  shopping_item_id: string;
  name: string;
  state: ShoppingItemState;
  category: string | null;
  quantity: Quantity | null;
  source_candidate_id: string | null;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface ShoppingListResponse {
  active: ShoppingListItemDto[];
  completed: ShoppingListItemDto[];
}

export interface ShoppingItemCreate {
  name: string;
  category?: string;
  quantity?: Quantity;
  note?: string;
}

export interface ShoppingItemPatch {
  name?: string;
  category?: string | null;
  quantity?: Quantity;
  state?: ShoppingItemState;
  note?: string | null;
}

export interface CandidatesResponse {
  candidates: ReplacementCandidateDto[];
}

export interface AcceptCandidateResponse {
  shopping_item: ShoppingListItemDto;
}

// --- Tarifler ---

export interface RecipeRecommendationDto {
  recipe_id: string;
  title: string;
  match_score: number;
  expiring_used_count: number;
  missing_required: string[];
  description: string | null;
  meal_types: string[];
  servings: number | null;
  prep_minutes: number | null;
  cook_minutes: number | null;
  allergen_tags: string[];
  diet_tags: string[];
}

export interface RecipesResponse {
  dataset_version: string;
  recommendations: RecipeRecommendationDto[];
}

// --- Cihaz kaydı (push — gönderim sonraki fazda) ---

export interface DeviceRegisterRequest {
  installation_id: string;
  push_token: string;
  platform?: string;
}
