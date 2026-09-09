import { useEffect, useState } from "react";
import type { InventoryItemDto } from "../api/types";
import type { UploadTicket } from "../hooks/useUpload";
import { buildCropStyle, loadImageSize } from "../lib/cropImage";
import { categoryLabel, subcategoryLabel } from "../lib/labels";

interface ExtractionResultProps {
  ticket: UploadTicket;
}

const COORD_MAX = 1000;

/**
 * Bir yükleme tamamlandığında Gemini'nin bulduğu ürünleri, kutularına göre
 * kaynak fotoğraftan kırpılmış AYRI görseller olarak gösterir. Bu, Faz 1'in
 * yeni özelliğinin test yüzeyidir: solda kaynak fotoğraf üstünde kutu
 * overlay'leri, sağda her ürünün tek tek kırpılmış hâli.
 *
 * Kırpma salt CSS ile yapılır (bkz. `lib/cropImage.ts`), CORS gerektirmez.
 * Doğru en-boy oranı için kaynak görselin doğal boyutu bir kez okunur.
 */
export function ExtractionResult({ ticket }: ExtractionResultProps) {
  const boxedItems = ticket.items.filter((item) => item.bounding_box);
  const [imageSize, setImageSize] = useState<{ width: number; height: number } | null>(null);
  const [imageError, setImageError] = useState(false);

  useEffect(() => {
    if (!ticket.sourceImageUrl || boxedItems.length === 0) return;

    let cancelled = false;
    setImageSize(null);
    setImageError(false);

    loadImageSize(ticket.sourceImageUrl)
      .then((size) => {
        if (!cancelled) setImageSize(size);
      })
      .catch(() => {
        if (!cancelled) setImageError(true);
      });

    return () => {
      cancelled = true;
    };
    // sourceImageUrl her yüklemede benzersiz; kutular onunla birlikte gelir.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticket.sourceImageUrl]);

  if (ticket.status !== "COMPLETED" || ticket.items.length === 0) {
    return null;
  }

  const noBoxItems = ticket.items.filter((item) => !item.bounding_box);

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="truncate text-sm font-medium text-slate-700 dark:text-slate-200">
          {ticket.fileName}
        </h3>
        <span className="shrink-0 text-xs text-slate-400">
          {ticket.items.length} ürün · {boxedItems.length} kutulu
        </span>
      </div>

      {ticket.sourceImageUrl && !imageError && boxedItems.length > 0 && (
        <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
          <SourcePreview sourceUrl={ticket.sourceImageUrl} items={boxedItems} />
          <CropGrid items={boxedItems} sourceUrl={ticket.sourceImageUrl} imageSize={imageSize} />
        </div>
      )}

      {boxedItems.length > 0 && (imageError || !ticket.sourceImageUrl) && (
        <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-300">
          Kaynak görsel alınamadı; kutular bulundu ama kırpma yapılamıyor.
        </p>
      )}

      {noBoxItems.length > 0 && (
        <div className="flex flex-col gap-1">
          <p className="text-xs font-medium text-slate-500 dark:text-slate-400">
            Kutusu olmayan ürünler
          </p>
          <ul className="flex flex-wrap gap-1.5">
            {noBoxItems.map((item) => (
              <li
                key={item.item_id}
                className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300"
              >
                {item.name}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Kaynak fotoğraf + her ürünün kutusunu gösteren overlay dikdörtgenleri. */
function SourcePreview({ sourceUrl, items }: { sourceUrl: string; items: InventoryItemDto[] }) {
  return (
    <div className="relative overflow-hidden rounded-lg border border-slate-200 dark:border-slate-700">
      <img src={sourceUrl} alt="Kaynak fotoğraf" className="block w-full" />
      {items.map((item, index) => {
        const box = item.bounding_box!;
        return (
          <div
            key={item.item_id}
            className="absolute rounded-sm border-2 border-emerald-400/90 bg-emerald-400/10"
            style={{
              left: `${(box.xmin / COORD_MAX) * 100}%`,
              top: `${(box.ymin / COORD_MAX) * 100}%`,
              width: `${((box.xmax - box.xmin) / COORD_MAX) * 100}%`,
              height: `${((box.ymax - box.ymin) / COORD_MAX) * 100}%`,
            }}
          >
            <span className="absolute -top-0.5 left-0 -translate-y-full rounded bg-emerald-500 px-1 text-[10px] font-medium text-white">
              {index + 1}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** Her ürünün ayrı kırpılmış görseli (salt CSS arka plan kırpması). */
function CropGrid({
  items,
  sourceUrl,
  imageSize,
}: {
  items: InventoryItemDto[];
  sourceUrl: string;
  imageSize: { width: number; height: number } | null;
}) {
  return (
    <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      {items.map((item, index) => {
        const minConfidence = item.confidence
          ? Math.min(item.confidence.name, item.confidence.category)
          : null;
        return (
          <li
            key={item.item_id}
            className="flex flex-col gap-1.5 rounded-lg border border-slate-200 p-2 dark:border-slate-700"
          >
            <div className="relative overflow-hidden rounded-md bg-slate-100 dark:bg-slate-800">
              {imageSize ? (
                <div
                  role="img"
                  aria-label={item.name}
                  className="w-full"
                  style={buildCropStyle(sourceUrl, item.bounding_box!, imageSize.width, imageSize.height)}
                />
              ) : (
                <div className="flex aspect-square w-full animate-pulse items-center justify-center text-[11px] text-slate-400">
                  kırpılıyor…
                </div>
              )}
              <span className="absolute left-1 top-1 rounded bg-emerald-500 px-1 text-[10px] font-medium text-white">
                {index + 1}
              </span>
              {item.needs_review && (
                <span className="absolute right-1 top-1 rounded-full bg-violet-500 px-1.5 py-0.5 text-[10px] font-medium text-white">
                  gözden geçir
                </span>
              )}
            </div>
            <div className="min-w-0">
              <p className="truncate text-xs font-medium text-slate-800 dark:text-slate-100">
                {item.name}
              </p>
              <p className="truncate text-[11px] text-slate-400">
                {categoryLabel(item.category)}
                {item.subcategory && ` · ${subcategoryLabel(item.subcategory)}`}
                {minConfidence !== null && ` · %${Math.round(minConfidence * 100)}`}
              </p>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
