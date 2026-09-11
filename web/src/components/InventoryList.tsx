import type { DiscardReason, InventoryItemDto, ItemPatch } from "../api/types";
import { ItemCard } from "./ItemCard";

interface InventoryListProps {
  items: InventoryItemDto[];
  isLoading: boolean;
  error: string | null;
  onUpdate: (itemId: string, patch: ItemPatch) => Promise<void>;
  onDelete: (itemId: string) => Promise<void>;
  onSwipe: (item: InventoryItemDto, type: "CONSUMED" | "DISCARDED", reason?: DiscardReason) => Promise<void>;
  onOpenAssessment: (item: InventoryItemDto) => void;
}

export function InventoryList({
  items,
  isLoading,
  error,
  onUpdate,
  onDelete,
  onSwipe,
  onOpenAssessment,
}: InventoryListProps) {
  if (error) {
    return (
      <p className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/40 dark:bg-rose-950/20 dark:text-rose-300">
        {error}
      </p>
    );
  }

  if (isLoading && items.length === 0) {
    return <p className="px-1 text-sm text-slate-400">Envanter yükleniyor…</p>;
  }

  if (items.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 px-6 py-10 text-center text-sm text-slate-400 dark:border-slate-700">
        Henüz envanterde ürün yok. Bir fotoğraf yükleyerek başlayın.
      </div>
    );
  }

  // Backend zaten GSI1'den etkin tazelik tarihine göre artan sırada döndürür;
  // burada ayrıca sıralama yapmıyoruz. Erişim deseni doğru tasarlandığı için
  // istemci tarafında sıralamaya gerek kalmıyor.
  return (
    <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {items.map((item) => (
        <ItemCard
          key={item.item_id}
          item={item}
          onUpdate={(patch) => onUpdate(item.item_id, patch)}
          onDelete={() => onDelete(item.item_id)}
          onSwipe={(type, reason) => onSwipe(item, type, reason)}
          onOpenAssessment={() => onOpenAssessment(item)}
        />
      ))}
    </ul>
  );
}
