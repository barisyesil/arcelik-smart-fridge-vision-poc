/**
 * Prompt Lab yerel dev sunucusu istemcisi.
 *
 * Üretim `client.ts`'den AYRIDIR: Cognito yok, Authorization header yok. Yalnız
 * yerel `playground/server.py`'a (varsayılan http://localhost:8900) konuşur.
 * Amaç prompt mühendisliği: sürüm dene, tam prompt'u gör, token/maliyet ölç.
 * Bu istemci üretim envanterine hiç dokunmaz.
 */

export interface PromptVersion {
  id: string;
  label: string;
  description: string;
  system_prompt: string;
  source: "builtin" | "saved";
  is_production: boolean;
  editable: boolean;
}

export interface ModelPricing {
  id: string;
  input_per_1m: number;
  output_per_1m: number;
  note: string;
}

export interface LabMeta {
  units: string[];
  categories: string[];
  subcategories: string[];
  package_states: string[];
  models: ModelPricing[];
  default_model: string;
  default_prompt_id: string | null;
  has_api_key: boolean;
}

export interface LabProduct {
  name: string;
  category: string;
  subcategory: string | null;
  brand: string | null;
  raw_label: string | null;
  package_state: string;
  quantity: { value: number; unit: string; value_max: number | null };
  confidence: { name: number; category: number };
  bounding_box: { ymin: number; xmin: number; ymax: number; xmax: number } | null;
}

export interface LabUsage {
  prompt_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface LabCost {
  input_usd: number;
  output_usd: number;
  total_usd: number;
  currency: string;
  model_known: boolean;
  input_per_1m: number;
  output_per_1m: number;
  note: string;
}

export interface ExtractResult {
  prompt_id: string;
  model: string;
  temperature: number;
  latency_ms: number;
  product_count: number;
  products: LabProduct[];
  usage: LabUsage;
  cost: LabCost;
  system_prompt: string;
  response_schema: unknown;
  raw_response: string;
}

export class LabError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "LabError";
    this.status = status;
  }
}

function base(url: string): string {
  return url.replace(/\/$/, "");
}

async function parse<T>(response: Response): Promise<T> {
  const text = await response.text();
  const body = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new LabError(body?.detail ?? response.statusText, response.status);
  }
  return body as T;
}

export async function fetchMeta(baseUrl: string): Promise<LabMeta> {
  return parse(await fetch(`${base(baseUrl)}/playground/meta`));
}

export async function fetchPrompts(baseUrl: string): Promise<PromptVersion[]> {
  const body = await parse<{ versions: PromptVersion[] }>(
    await fetch(`${base(baseUrl)}/playground/prompts`),
  );
  return body.versions;
}

export async function savePrompt(
  baseUrl: string,
  version: { id: string; label: string; description: string; system_prompt: string },
): Promise<PromptVersion> {
  return parse(
    await fetch(`${base(baseUrl)}/playground/prompts`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(version),
    }),
  );
}

export async function deletePrompt(baseUrl: string, id: string): Promise<void> {
  await parse(
    await fetch(`${base(baseUrl)}/playground/prompts/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  );
}

export async function runExtract(
  baseUrl: string,
  params: {
    image: File;
    promptId?: string;
    systemPrompt?: string;
    model: string;
    temperature: number;
  },
): Promise<ExtractResult> {
  const form = new FormData();
  form.append("image", params.image);
  if (params.promptId) form.append("prompt_id", params.promptId);
  if (params.systemPrompt) form.append("system_prompt", params.systemPrompt);
  form.append("model", params.model);
  form.append("temperature", String(params.temperature));

  return parse(
    await fetch(`${base(baseUrl)}/playground/extract`, { method: "POST", body: form }),
  );
}
