/**
 * API kontratı v1'in TypeScript karşılığı. Alan adı/tipi değişecekse önce
 * backend tarafında, sonra burada değişir.
 */

export type UploadStatusValue = "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";

export type FreshnessBasis = "CATEGORY_HEURISTIC" | "USER_PROVIDED";

export type PackageState = "unopened" | "opened" | "unknown";

export type ItemState = "ACTIVE" | "CONSUMED" | "DISCARDED";

export type QuantityUnit = "piece" | "pack" | "bottle" | "gram" | "milliliter";

export interface Quantity {
  value: number;
  unit: QuantityUnit;
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
  name: string;
  brand: string | null;
  raw_label: string | null;
  category: string;
  subcategory: string | null;
  package_state: PackageState;
  quantity: Quantity;
  estimated_freshness_date: string;
  freshness_basis: FreshnessBasis;
  confidence: FieldConfidence | null;
  needs_review: boolean;
  state: ItemState;
  bounding_box: BoundingBox | null;
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
