import type {
  CreateUploadResponse,
  InventoryItemDto,
  ItemListResponse,
  ItemPatch,
  UploadStatusResponse,
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
 * İstemci bu iki değeri kendi seçer (localStorage'da tutulur, bkz.
 * `hooks/useSettings.ts`). Kimlik doğrulama yoktur; `x-user-id` header'ı
 * kullanıcı ayrımını sağlayan tek yerdir.
 */
export interface ApiConfig {
  baseUrl: string;
  userId: string;
}

async function request<T>(
  config: ApiConfig,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${config.baseUrl.replace(/\/$/, "")}${path}`, {
    ...init,
    headers: {
      "x-user-id": config.userId,
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

export function createUpload(config: ApiConfig): Promise<CreateUploadResponse> {
  return request(config, "/v1/uploads", { method: "POST" });
}

export function getUploadStatus(
  config: ApiConfig,
  uploadId: string,
): Promise<UploadStatusResponse> {
  return request(config, `/v1/uploads/${encodeURIComponent(uploadId)}`);
}

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

/**
 * Presigned POST ile S3'e doğrudan yükleme — API Gateway'den geçmez, çünkü
 * 5 MB'lık dosya Lambda payload limitini aşar. Bu çağrı `ApiConfig` almaz;
 * S3 kendi imzalı URL'sinden çalışır.
 */
export async function uploadToS3(
  presign: CreateUploadResponse,
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
