import { useEffect, useMemo, useRef, useState } from "react";
import type { ExtractResult, LabProduct, PromptVersion } from "../api/playground";
import { usePromptLab } from "../hooks/usePromptLab";
import { categoryLabel, formatQuantity, packageStateLabel } from "../lib/labels";

interface PromptLabProps {
  onExit: () => void;
}

/**
 * AI mühendisi çalışma ortamı. Yerel `playground` sunucusuna konuşur; üretim
 * cloud API'sinden ve Cognito'dan bağımsızdır. Prompt sürümü seç/düzenle,
 * görsel yükle, modele giden TAM prompt'u + token + tahmini maliyeti gör.
 */
export function PromptLab({ onExit }: PromptLabProps) {
  const lab = usePromptLab();
  const [selectedId, setSelectedId] = useState<string>("");
  const [promptText, setPromptText] = useState<string>("");
  const [dirty, setDirty] = useState(false);
  const [model, setModel] = useState<string>("gemini-2.5-flash");
  const [temperature, setTemperature] = useState(0.1);
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const selected: PromptVersion | undefined = useMemo(
    () => lab.prompts.find((p) => p.id === selectedId),
    [lab.prompts, selectedId],
  );

  // İlk yükte / sürümler gelince varsayılan sürümü seç ve editörü doldur.
  useEffect(() => {
    if (lab.prompts.length === 0) return;
    const initial =
      lab.prompts.find((p) => p.id === (lab.meta?.default_prompt_id ?? "")) ?? lab.prompts[0];
    setSelectedId((cur) => (cur && lab.prompts.some((p) => p.id === cur) ? cur : initial.id));
  }, [lab.prompts, lab.meta]);

  useEffect(() => {
    if (selected) {
      setPromptText(selected.system_prompt);
      setDirty(false);
    }
  }, [selected]);

  useEffect(() => {
    if (lab.meta?.default_model) setModel(lab.meta.default_model);
  }, [lab.meta]);

  const onPickFile = (f: File | null) => {
    setFile(f);
    setPreviewUrl((old) => {
      if (old) URL.revokeObjectURL(old);
      return f ? URL.createObjectURL(f) : null;
    });
  };

  const handleRun = () => {
    if (!file) return;
    void lab.run({
      image: file,
      // Editörde metin değiştiyse ham metni gönder; değilse sürüm id'sini.
      promptId: selectedId,
      systemPrompt: dirty ? promptText : undefined,
      model,
      temperature,
    });
  };

  const handleSaveAs = async () => {
    const id = window.prompt("Yeni sürüm id (küçük harf, örn. exp-v4-koli):");
    if (!id) return;
    const label = window.prompt("Görünen ad:", id) ?? id;
    try {
      await lab.save({ id, label, description: "", system_prompt: promptText });
      setSelectedId(id.trim().toLowerCase());
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "Kaydedilemedi");
    }
  };

  const handleDelete = async () => {
    if (!selected || !selected.editable) return;
    if (!window.confirm(`'${selected.label}' silinsin mi?`)) return;
    await lab.remove(selected.id);
    setSelectedId("");
  };

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-5 px-4 py-6 sm:px-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col gap-0.5">
          <h1 className="flex items-center gap-2 text-xl font-semibold text-slate-900 dark:text-white">
            🧪 Prompt Lab
            <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:bg-amber-950 dark:text-amber-300">
              yerel dev aracı
            </span>
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Prompt sürümlerini dene · tam prompt, token ve tahmini maliyeti gör
          </p>
        </div>
        <button
          type="button"
          onClick={onExit}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          ← Uygulamaya dön
        </button>
      </header>

      <ServerBar
        url={lab.serverUrl}
        onChange={lab.setServerUrl}
        onRefresh={() => void lab.refresh()}
        loading={lab.loading}
        connError={lab.connError}
        hasKey={lab.meta?.has_api_key ?? false}
      />

      {lab.connError && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300">
          {lab.connError}
          <div className="mt-1 text-xs text-rose-500 dark:text-rose-400">
            Sunucuyu başlat:{" "}
            <code className="rounded bg-rose-100 px-1 dark:bg-rose-900/50">
              uvicorn playground.server:app --port 8900
            </code>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* Sol: prompt seç + düzenle + çalıştır */}
        <section className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <label className="text-xs font-medium text-slate-600 dark:text-slate-300">
              Prompt sürümü
            </label>
            <select
              value={selectedId}
              onChange={(e) => setSelectedId(e.target.value)}
              className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
            >
              {lab.prompts.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.is_production ? "★ " : p.source === "saved" ? "✎ " : "◦ "}
                  {p.label}
                </option>
              ))}
            </select>
            {selected?.description && (
              <p className="text-xs text-slate-500 dark:text-slate-400">{selected.description}</p>
            )}
            {selected?.is_production && (
              <p className="text-xs text-emerald-600 dark:text-emerald-400">
                Bu üretim promptu — mobil ve gerçek sistem bunu kullanır. Düzenlemek için
                "Yeni sürüm olarak kaydet".
              </p>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <label className="text-xs font-medium text-slate-600 dark:text-slate-300">
                Sistem promptu {dirty && <span className="text-amber-500">· düzenlendi</span>}
              </label>
              <span className="text-[11px] text-slate-400">{promptText.length} karakter</span>
            </div>
            <textarea
              value={promptText}
              onChange={(e) => {
                setPromptText(e.target.value);
                setDirty(true);
              }}
              rows={14}
              spellCheck={false}
              className="rounded-md border border-slate-300 bg-white px-3 py-2 font-mono text-xs leading-relaxed dark:border-slate-700 dark:bg-slate-900"
            />
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => void handleSaveAs()}
                className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-200"
              >
                Yeni sürüm olarak kaydet
              </button>
              {selected && (
                <button
                  type="button"
                  onClick={() => selected && setPromptText(selected.system_prompt)}
                  className="rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  Sıfırla
                </button>
              )}
              {selected?.editable && (
                <button
                  type="button"
                  onClick={() => void handleDelete()}
                  className="rounded-md border border-rose-300 px-3 py-1.5 text-xs text-rose-600 hover:bg-rose-50 dark:border-rose-900 dark:text-rose-400 dark:hover:bg-rose-950/40"
                >
                  Sil
                </button>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-slate-600 dark:text-slate-300">Model</label>
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
              >
                {(lab.meta?.models ?? [{ id: "gemini-2.5-flash" }]).map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.id}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-slate-600 dark:text-slate-300">
                Sıcaklık: {temperature.toFixed(2)}
              </label>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={temperature}
                onChange={(e) => setTemperature(Number(e.target.value))}
                className="mt-2 accent-slate-900 dark:accent-white"
              />
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <label className="text-xs font-medium text-slate-600 dark:text-slate-300">Görsel</label>
            <button
              type="button"
              onClick={() => fileInput.current?.click()}
              className="rounded-md border-2 border-dashed border-slate-300 px-4 py-3 text-sm text-slate-500 hover:border-slate-400 dark:border-slate-700"
            >
              {file ? file.name : "Fotoğraf seç (JPEG/PNG)"}
            </button>
            <input
              ref={fileInput}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => onPickFile(e.target.files?.[0] ?? null)}
            />
            <button
              type="button"
              disabled={!file || lab.running || !!lab.connError}
              onClick={handleRun}
              className="rounded-md bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {lab.running ? "Çalışıyor…" : "Çalıştır ▸"}
            </button>
            {lab.runError && (
              <p className="text-xs text-rose-600 dark:text-rose-400">{lab.runError}</p>
            )}
          </div>
        </section>

        {/* Sağ: sonuç */}
        <section className="flex flex-col gap-4">
          <ResultView result={lab.result} previewUrl={previewUrl} />
        </section>
      </div>
    </div>
  );
}

function ServerBar({
  url,
  onChange,
  onRefresh,
  loading,
  connError,
  hasKey,
}: {
  url: string;
  onChange: (u: string) => void;
  onRefresh: () => void;
  loading: boolean;
  connError: string | null;
  hasKey: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-800 dark:bg-slate-900">
      <span className="text-xs text-slate-500">Sunucu</span>
      <input
        value={url}
        onChange={(e) => onChange(e.target.value)}
        className="min-w-52 flex-1 rounded border border-slate-300 px-2 py-1 font-mono text-xs dark:border-slate-700 dark:bg-slate-950"
      />
      <span
        className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] ${
          connError
            ? "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300"
            : "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
        }`}
      >
        {connError ? "bağlantı yok" : "bağlı"}
      </span>
      {!connError && (
        <span
          className={`rounded px-2 py-0.5 text-[11px] ${
            hasKey
              ? "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
              : "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300"
          }`}
        >
          {hasKey ? "API anahtarı var" : "API anahtarı yok"}
        </span>
      )}
      <button
        type="button"
        onClick={onRefresh}
        className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
      >
        {loading ? "…" : "Yenile"}
      </button>
    </div>
  );
}

function ResultView({
  result,
  previewUrl,
}: {
  result: ExtractResult | null;
  previewUrl: string | null;
}) {
  if (!result) {
    return (
      <div className="flex h-full min-h-40 items-center justify-center rounded-xl border border-dashed border-slate-300 text-sm text-slate-400 dark:border-slate-700">
        Sonuç burada görünecek — bir görsel seçip Çalıştır'a bas.
      </div>
    );
  }

  const usd = (n: number) => `$${n.toFixed(6)}`;

  return (
    <div className="flex flex-col gap-4">
      {/* Metrik kartları */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Metric label="Süre" value={`${result.latency_ms} ms`} />
        <Metric label="Ürün grubu" value={String(result.product_count)} />
        <Metric label="Token (top.)" value={String(result.usage.total_tokens)} />
        <Metric
          label="Tahmini maliyet"
          value={usd(result.cost.total_usd)}
          hint={result.cost.model_known ? result.cost.note : "model fiyatı bilinmiyor"}
        />
      </div>
      <div className="grid grid-cols-3 gap-2 text-center text-xs text-slate-500 dark:text-slate-400">
        <span>girdi: {result.usage.prompt_tokens} tok · {usd(result.cost.input_usd)}</span>
        <span>çıktı: {result.usage.output_tokens} tok · {usd(result.cost.output_usd)}</span>
        <span>{result.model} · sıc. {result.temperature}</span>
      </div>

      {previewUrl && <BoxPreview src={previewUrl} products={result.products} />}

      {/* Ürün grupları */}
      <div className="flex flex-col gap-2">
        <h3 className="text-xs font-medium text-slate-600 dark:text-slate-300">
          Ürün grupları ({result.products.length})
        </h3>
        {result.products.length === 0 && (
          <p className="text-sm text-slate-400">Ürün bulunamadı.</p>
        )}
        {result.products.map((p, i) => (
          <ProductRow key={i} product={p} />
        ))}
      </div>

      <Collapsible title="Modele giden tam sistem promptu">
        <pre className="whitespace-pre-wrap break-words rounded bg-slate-100 p-3 font-mono text-[11px] dark:bg-slate-900">
          {result.system_prompt}
        </pre>
      </Collapsible>
      <Collapsible title="Ham model yanıtı (JSON)">
        <pre className="overflow-x-auto rounded bg-slate-100 p-3 font-mono text-[11px] dark:bg-slate-900">
          {result.raw_response}
        </pre>
      </Collapsible>
      <Collapsible title="Yanıt şeması (response_schema)">
        <pre className="overflow-x-auto rounded bg-slate-100 p-3 font-mono text-[11px] dark:bg-slate-900">
          {JSON.stringify(result.response_schema, null, 2)}
        </pre>
      </Collapsible>
    </div>
  );
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
      <div className="text-[11px] text-slate-500 dark:text-slate-400">{label}</div>
      <div className="text-sm font-semibold text-slate-900 dark:text-white">{value}</div>
      {hint && <div className="text-[10px] text-slate-400">{hint}</div>}
    </div>
  );
}

function ProductRow({ product }: { product: LabProduct }) {
  const conf = Math.min(product.confidence.name, product.confidence.category);
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-800 dark:bg-slate-900">
      <span className="font-medium text-slate-900 dark:text-white">{product.name}</span>
      {product.brand && <span className="text-xs text-slate-400">{product.brand}</span>}
      <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
        {formatQuantity(product.quantity)}
        {product.quantity.value_max != null && product.quantity.value_max > product.quantity.value
          ? " (tahmini)"
          : ""}
      </span>
      <span className="text-xs text-slate-500">{categoryLabel(product.category)}</span>
      <span className="text-xs text-slate-400">{packageStateLabel(product.package_state)}</span>
      <span
        className={`ml-auto text-xs ${
          conf < 0.6 ? "text-amber-600 dark:text-amber-400" : "text-slate-400"
        }`}
      >
        güven {(conf * 100).toFixed(0)}%
      </span>
      {!product.bounding_box && <span className="text-[10px] text-slate-400">kutu yok</span>}
    </div>
  );
}

/** Görselin üzerine ürün grubu kutularını çizer (0-1000 ölçeği). */
function BoxPreview({ src, products }: { src: string; products: LabProduct[] }) {
  const boxed = products.filter((p) => p.bounding_box);
  return (
    <div className="relative overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
      <img src={src} alt="yüklenen" className="block w-full" />
      {boxed.map((p, i) => {
        const b = p.bounding_box!;
        return (
          <div
            key={i}
            className="absolute border-2 border-emerald-400/90"
            style={{
              left: `${(b.xmin / 1000) * 100}%`,
              top: `${(b.ymin / 1000) * 100}%`,
              width: `${((b.xmax - b.xmin) / 1000) * 100}%`,
              height: `${((b.ymax - b.ymin) / 1000) * 100}%`,
            }}
          >
            <span className="absolute -top-0.5 left-0 -translate-y-full bg-emerald-500 px-1 text-[10px] text-white">
              {p.name} · {formatQuantity(p.quantity)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function Collapsible({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-800">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-3 py-2 text-xs font-medium text-slate-600 dark:text-slate-300"
      >
        {title}
        <span className="text-slate-400">{open ? "−" : "+"}</span>
      </button>
      {open && <div className="border-t border-slate-200 p-2 dark:border-slate-800">{children}</div>}
    </div>
  );
}
