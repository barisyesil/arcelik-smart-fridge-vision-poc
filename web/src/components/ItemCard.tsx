import { useState } from "react";
import type { DiscardReason, InventoryItemDto, ItemPatch } from "../api/types";
import { daysUntil, formatDaysLeft, urgencyOf } from "../lib/freshness";
import { categoryLabel, packageStateLabel, quantityUnitLabel, subcategoryLabel } from "../lib/labels";

interface ItemCardProps {
  item: InventoryItemDto;
  onUpdate: (patch: ItemPatch) => Promise<void>;
  onDelete: () => Promise<void>;
  /** Tükettim/Attım — swipe aksiyonu olarak sunucuya gider (idempotent,
   * geri alınabilir). Doğrudan `state` PATCH'i DEĞİLDİR: sunucu tarafında
   * `SwipeAction` olayı + `ReplacementCandidate` üretir. */
  onSwipe: (type: "CONSUMED" | "DISCARDED", reason?: DiscardReason) => Promise<void>;
  /** "Kontrol Et" — yukarı swipe karşılığı: değerlendirme panelini açar. */
  onOpenAssessment: () => void;
}

const URGENCY_STYLES: Record<string, string> = {
  expired: "border-rose-300 bg-rose-50 dark:border-rose-900/50 dark:bg-rose-950/20",
  soon: "border-amber-300 bg-amber-50 dark:border-amber-900/50 dark:bg-amber-950/20",
  ok: "border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900",
};

const URGENCY_TEXT: Record<string, string> = {
  expired: "text-rose-700 dark:text-rose-300",
  soon: "text-amber-700 dark:text-amber-300",
  ok: "text-slate-500 dark:text-slate-400",
};

const DISCARD_REASONS: { value: DiscardReason; label: string }[] = [
  { value: "OVERPURCHASED", label: "Gereğinden fazla alındı" },
  { value: "NO_OPPORTUNITY_TO_CONSUME", label: "Tüketmeye fırsat olmadı" },
  { value: "SPOILED_EARLIER_THAN_EXPECTED", label: "Beklenenden erken bozuldu" },
  { value: "IMPROPER_STORAGE", label: "Saklama koşulu uygun değildi" },
  { value: "WRONG_DETECTION", label: "Ürün yanlış tanındı" },
  { value: "OTHER", label: "Diğer" },
];

export function ItemCard({ item, onUpdate, onDelete, onSwipe, onOpenAssessment }: ItemCardProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [draftName, setDraftName] = useState(item.name);
  const [isBusy, setIsBusy] = useState(false);
  const [isPickingReason, setIsPickingReason] = useState(false);

  // Kullanıcı düzeltmesi varsa etkin tarih ondan gelir (BR-002); sistem
  // tahmini ayrı gösterilir ki ikisi karışmasın.
  const daysLeft = daysUntil(item.effective_fresh_until);
  const urgency = urgencyOf(daysLeft);

  const runAction = async (action: () => Promise<void>) => {
    setIsBusy(true);
    try {
      await action();
    } finally {
      setIsBusy(false);
    }
  };

  const minConfidence = item.confidence
    ? Math.min(item.confidence.name, item.confidence.category)
    : null;

  return (
    <li className={`flex flex-col gap-2.5 rounded-xl border p-4 ${URGENCY_STYLES[urgency]}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          {isEditing ? (
            <input
              autoFocus
              value={draftName}
              onChange={(e) => setDraftName(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm font-medium dark:border-slate-700 dark:bg-slate-950"
            />
          ) : (
            <p className="truncate font-medium text-slate-900 dark:text-white">
              {item.name}
              {item.brand && <span className="ml-1.5 font-normal text-slate-400">· {item.brand}</span>}
            </p>
          )}
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {categoryLabel(item.category)}
            {item.subcategory && ` · ${subcategoryLabel(item.subcategory)}`}
          </p>
        </div>
        {item.needs_review && (
          <span className="shrink-0 rounded-full bg-violet-100 px-2 py-0.5 text-[11px] font-medium text-violet-700 dark:bg-violet-950/40 dark:text-violet-300">
            gözden geçir
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
        <span>
          {item.quantity.value} {quantityUnitLabel(item.quantity.unit)}
        </span>
        <span>·</span>
        <span>{packageStateLabel(item.package_state)}</span>
        {minConfidence !== null && (
          <>
            <span>·</span>
            <span>güven %{Math.round(minConfidence * 100)}</span>
          </>
        )}
      </div>

      <div>
        <p className={`text-sm font-medium ${URGENCY_TEXT[urgency]}`}>{formatDaysLeft(daysLeft)}</p>
        {item.user_adjusted_fresh_until && (
          <p className="text-[11px] text-slate-400">
            Sistem tahmini: {item.predicted_fresh_until} · senin değerlendirmen esas alınıyor
          </p>
        )}
      </div>

      {isPickingReason ? (
        <div className="flex flex-col gap-1.5 rounded-md border border-slate-200 p-2 dark:border-slate-700">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Bu ürünü kullanamamanın temel nedeni neydi? (isteğe bağlı)
          </p>
          <div className="flex flex-wrap gap-1.5">
            {DISCARD_REASONS.map((r) => (
              <button
                key={r.value}
                type="button"
                disabled={isBusy}
                onClick={() =>
                  runAction(async () => {
                    await onSwipe("DISCARDED", r.value);
                    setIsPickingReason(false);
                  })
                }
                className="rounded-full border border-slate-300 px-2.5 py-1 text-[11px] text-slate-600 hover:bg-slate-50 disabled:opacity-40 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                {r.label}
              </button>
            ))}
            <button
              type="button"
              disabled={isBusy}
              onClick={() => runAction(() => onSwipe("DISCARDED"))}
              className="rounded-full px-2.5 py-1 text-[11px] text-slate-400 hover:text-slate-600 disabled:opacity-40"
            >
              Belirtmek istemiyorum
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-1 flex flex-wrap gap-1.5">
          {isEditing ? (
            <>
              <button
                type="button"
                disabled={isBusy || draftName.trim().length === 0}
                onClick={() =>
                  runAction(async () => {
                    await onUpdate({ name: draftName.trim() });
                    setIsEditing(false);
                  })
                }
                className="rounded-md bg-slate-900 px-2.5 py-1 text-xs font-medium text-white disabled:opacity-40 dark:bg-white dark:text-slate-900"
              >
                Kaydet
              </button>
              <button
                type="button"
                onClick={() => {
                  setDraftName(item.name);
                  setIsEditing(false);
                }}
                className="rounded-md border border-slate-300 px-2.5 py-1 text-xs text-slate-600 dark:border-slate-700 dark:text-slate-300"
              >
                Vazgeç
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                disabled={isBusy}
                onClick={() => runAction(() => onSwipe("CONSUMED"))}
                className="rounded-md border border-emerald-300 px-2.5 py-1 text-xs text-emerald-700 hover:bg-emerald-50 disabled:opacity-40 dark:border-emerald-800 dark:text-emerald-300 dark:hover:bg-emerald-950/30"
              >
                Tükettim
              </button>
              <button
                type="button"
                disabled={isBusy}
                onClick={() => setIsPickingReason(true)}
                className="rounded-md border border-slate-300 px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                Attım
              </button>
              <button
                type="button"
                disabled={isBusy}
                onClick={onOpenAssessment}
                className="rounded-md border border-slate-300 px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                Kontrol Et
              </button>
              <button
                type="button"
                disabled={isBusy}
                onClick={() => setIsEditing(true)}
                className="rounded-md border border-slate-300 px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                Düzelt
              </button>
              <button
                type="button"
                disabled={isBusy}
                onClick={() => runAction(onDelete)}
                className="ml-auto rounded-md px-2.5 py-1 text-xs text-rose-500 hover:bg-rose-50 disabled:opacity-40 dark:hover:bg-rose-950/30"
              >
                Sil
              </button>
            </>
          )}
        </div>
      )}
    </li>
  );
}
