import type { DiscardReason, InventoryItemDto, ItemPatch, ReviewQueueEntryDto } from "../api/types";
import { reviewReasonLabel } from "../lib/labels";
import { ItemCard } from "./ItemCard";

interface ReviewQueuePanelProps {
  entries: ReviewQueueEntryDto[];
  totalPending: number;
  isLoading: boolean;
  error: string | null;
  onUpdate: (itemId: string, patch: ItemPatch) => Promise<void>;
  onDelete: (itemId: string) => Promise<void>;
  onSwipe: (
    item: InventoryItemDto,
    type: "CONSUMED" | "DISCARDED",
    reason?: DiscardReason,
  ) => Promise<void>;
  onOpenAssessment: (item: InventoryItemDto) => void;
}

/**
 * Mobil "Kontrol / Swipe Kart Modu"nun web karşılığı (SRS 8.7). Kartlar
 * yerine liste kullanılır ama BR-004 önceliği backend'den geldiği gibi
 * korunur — sıralama burada değiştirilmez.
 */
export function ReviewQueuePanel({
  entries,
  totalPending,
  isLoading,
  error,
  onUpdate,
  onDelete,
  onSwipe,
  onOpenAssessment,
}: ReviewQueuePanelProps) {
  if (error) {
    return (
      <p className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/40 dark:bg-rose-950/20 dark:text-rose-300">
        {error}
      </p>
    );
  }

  if (isLoading && entries.length === 0) {
    return <p className="px-1 text-sm text-slate-400">Kontrol kuyruğu yükleniyor…</p>;
  }

  if (entries.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 px-6 py-10 text-center text-sm text-slate-400 dark:border-slate-700">
        Bugün kontrol bekleyen ürün yok. Dolabın güncel.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-slate-500 dark:text-slate-400">
        Bugünkü Kontrol — {totalPending} ürün bekliyor
      </p>
      <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {entries.map((entry) => (
          <div key={entry.item_id} className="flex flex-col gap-1">
            <span className="self-start rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              {reviewReasonLabel(entry.reason)}
            </span>
            <ItemCard
              item={entry.item}
              onUpdate={(patch) => onUpdate(entry.item_id, patch)}
              onDelete={() => onDelete(entry.item_id)}
              onSwipe={(type, reason) => onSwipe(entry.item, type, reason)}
              onOpenAssessment={() => onOpenAssessment(entry.item)}
            />
          </div>
        ))}
      </ul>
    </div>
  );
}
