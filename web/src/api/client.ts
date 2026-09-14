import type {
  AcceptCandidateResponse,
  AssessmentResponse,
  CandidatesResponse,
  ConfirmItem,
  ConfirmUploadResponse,
  CreateCropUploadResponse,
  CreateUploadResponse,
  DeviceRegisterRequest,
  FreshnessAssessmentRequest,
  InventoryItemDto,
  ItemListResponse,
  ItemPatch,
  NotificationPreferencesDto,
  RecipesResponse,
  RegisterProfileRequest,
  ReplacementCandidateStatus,
  ReviewQueueResponse,
  ShoppingItemCreate,
  ShoppingItemPatch,
  ShoppingListItemDto,
  ShoppingListResponse,
  SwipeActionRequest,
  SwipeActionResponse,
  UndoActionResponse,
  UploadStatusResponse,
  UserProfileDto,
} from "./types";

export class ApiRequestError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
  }
}

/**
 * `baseUrl` deploy'a özel API adresidir. Kimlik `getIdToken` üzerinden gelir —
 * Cognito Hosted UI PKCE akışının ürettiği `id_token` (bkz. `hooks/useAuth.ts`).
 * Backend kimliği yalnızca bu token'ın doğrulanmış `sub` claim'inden okur;
 * istemci tarafında ayrıca bir kullanıcı kimliği TUTULMAZ.
 */
export interface ApiConfig {
  baseUrl: string;
  getIdToken: () => Promise<string | null>;
}

async function request<T>(config: ApiConfig, path: string, init?: RequestInit): Promise<T> {
  const token = await config.getIdToken();
  if (!token) {
    throw new ApiRequestError("Oturum yok — lütfen giriş yapın.", 401);
  }

  const response = await fetch(`${config.baseUrl.replace(/\/$/, "")}${path}`, {
    ...init,
    headers: {
      authorization: `Bearer ${token}`,
      ...(init?.body ? { "content-type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  const body = text ? JSON.parse(text) : {};

  if (!response.ok) {
    throw new ApiRequestError(body?.detail ?? body?.error ?? response.statusText, response.status);
  }

  return body as T;
}

// --- Profil & bildirim ---

export function getMe(config: ApiConfig): Promise<UserProfileDto> {
  return request(config, "/v1/users/me");
}

export function registerProfile(
  config: ApiConfig,
  body: RegisterProfileRequest,
): Promise<UserProfileDto> {
  return request(config, "/v1/users/me", { method: "PUT", body: JSON.stringify(body) });
}

export function putNotificationPreferences(
  config: ApiConfig,
  prefs: Partial<NotificationPreferencesDto>,
): Promise<NotificationPreferencesDto> {
  return request(config, "/v1/users/me/notification-preferences", {
    method: "PUT",
    body: JSON.stringify(prefs),
  });
}

export function registerDevice(config: ApiConfig, body: DeviceRegisterRequest): Promise<void> {
  return request(config, "/v1/devices", { method: "POST", body: JSON.stringify(body) });
}

export function unregisterDevice(config: ApiConfig, installationId: string): Promise<void> {
  return request(config, `/v1/devices/${encodeURIComponent(installationId)}`, {
    method: "DELETE",
  });
}

// --- Yükleme ---

export function createUpload(config: ApiConfig): Promise<CreateUploadResponse> {
  return request(config, "/v1/uploads", { method: "POST" });
}

export function getUploadStatus(
  config: ApiConfig,
  uploadId: string,
): Promise<UploadStatusResponse> {
  return request(config, `/v1/uploads/${encodeURIComponent(uploadId)}`);
}

/** Kontrol ekranı onayında bir ürünün kırpılmış görselini yüklemek için presigned POST alır. */
export function createCropUpload(
  config: ApiConfig,
  uploadId: string,
): Promise<CreateCropUploadResponse> {
  return request(config, `/v1/uploads/${encodeURIComponent(uploadId)}/crops`, { method: "POST" });
}

/** Kontrol ekranı onayı: seçili DRAFT ürünleri (crop + düzenlemelerle) ACTIVE yapar. */
export function confirmUpload(
  config: ApiConfig,
  uploadId: string,
  confirmed: ConfirmItem[],
): Promise<ConfirmUploadResponse> {
  return request(config, `/v1/uploads/${encodeURIComponent(uploadId)}/confirm`, {
    method: "POST",
    body: JSON.stringify({ confirmed }),
  });
}

// --- Envanter ---

export function listItems(config: ApiConfig): Promise<ItemListResponse> {
  return request(config, "/v1/items");
}

export function patchItem(
  config: ApiConfig,
  itemId: string,
  patch: ItemPatch,
): Promise<InventoryItemDto> {
  return request(config, `/v1/items/${encodeURIComponent(itemId)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteItem(config: ApiConfig, itemId: string): Promise<void> {
  return request(config, `/v1/items/${encodeURIComponent(itemId)}`, { method: "DELETE" });
}

// --- Swipe aksiyonları ---

export function postItemAction(
  config: ApiConfig,
  itemId: string,
  body: SwipeActionRequest,
): Promise<SwipeActionResponse> {
  return request(config, `/v1/items/${encodeURIComponent(itemId)}/actions`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function undoAction(config: ApiConfig, actionId: string): Promise<UndoActionResponse> {
  return request(config, `/v1/item-actions/${encodeURIComponent(actionId)}/undo`, {
    method: "POST",
  });
}

export function postAssessment(
  config: ApiConfig,
  itemId: string,
  body: FreshnessAssessmentRequest,
): Promise<AssessmentResponse> {
  return request(config, `/v1/items/${encodeURIComponent(itemId)}/freshness-assessments`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// --- Kontrol kuyruğu ---

export function getReviewQueue(config: ApiConfig): Promise<ReviewQueueResponse> {
  return request(config, "/v1/review-queue");
}

// --- Alışveriş listesi ---

export function getShoppingList(config: ApiConfig): Promise<ShoppingListResponse> {
  return request(config, "/v1/shopping-lists/current");
}

export function postShoppingItem(
  config: ApiConfig,
  body: ShoppingItemCreate,
): Promise<ShoppingListItemDto> {
  return request(config, "/v1/shopping-lists/current/items", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function patchShoppingItem(
  config: ApiConfig,
  shoppingItemId: string,
  patch: ShoppingItemPatch,
): Promise<ShoppingListItemDto> {
  return request(config, `/v1/shopping-lists/current/items/${encodeURIComponent(shoppingItemId)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteShoppingItem(config: ApiConfig, shoppingItemId: string): Promise<void> {
  return request(config, `/v1/shopping-lists/current/items/${encodeURIComponent(shoppingItemId)}`, {
    method: "DELETE",
  });
}

// --- Replacement candidates ---

export function getCandidates(
  config: ApiConfig,
  status?: ReplacementCandidateStatus,
): Promise<CandidatesResponse> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return request(config, `/v1/replacement-candidates${qs}`);
}

export function acceptCandidate(
  config: ApiConfig,
  candidateId: string,
): Promise<AcceptCandidateResponse> {
  return request(config, `/v1/replacement-candidates/${encodeURIComponent(candidateId)}/accept`, {
    method: "POST",
  });
}

export function dismissCandidate(config: ApiConfig, candidateId: string): Promise<void> {
  return request(config, `/v1/replacement-candidates/${encodeURIComponent(candidateId)}/dismiss`, {
    method: "POST",
  });
}

// --- Tarifler ---

export function getRecipes(
  config: ApiConfig,
  params?: { allergens?: string[]; diets?: string[]; mealType?: string; maxPrepMinutes?: number },
): Promise<RecipesResponse> {
  const qs = new URLSearchParams();
  if (params?.allergens?.length) qs.set("allergens", params.allergens.join(","));
  if (params?.diets?.length) qs.set("diets", params.diets.join(","));
  if (params?.mealType) qs.set("meal_type", params.mealType);
  if (params?.maxPrepMinutes) qs.set("max_prep_minutes", String(params.maxPrepMinutes));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return request(config, `/v1/recipes/recommendations${suffix}`);
}

/**
 * Presigned POST ile S3'e doğrudan yükleme — API Gateway'den geçmez, çünkü
 * 5 MB'lık dosya Lambda payload limitini aşar. Bu çağrı `ApiConfig` almaz;
 * S3 kendi imzalı URL'sinden çalışır ve kimlik gerektirmez.
 */
export async function uploadToS3(
  presign: { url: string; fields: Record<string, string> },
  file: Blob,
  contentType: string,
): Promise<void> {
  const form = new FormData();
  for (const [key, value] of Object.entries(presign.fields)) {
    form.append(key, value);
  }
  form.append("Content-Type", contentType);
  form.append("file", file);

  const response = await fetch(presign.url, { method: "POST", body: form });
  if (!response.ok) {
    throw new ApiRequestError(`S3 yüklemesi başarısız oldu (${response.status})`, response.status);
  }
}
