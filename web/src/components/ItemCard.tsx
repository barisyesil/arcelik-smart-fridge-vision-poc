import { useState } from "react";
import type { InventoryItemDto, ItemPatch } from "../api/types";
import { daysUntil, formatDaysLeft, urgencyOf } from "../lib/freshness";
import { categoryLabel, packageStateLabel, quantityUnitLabel, subcategoryLabel } from "../lib/labels";

interface ItemCardProps {
  item: InventoryItemDto;
  onUpdate: (patch: ItemPatch) => Promise<void>;
  onDelete: () => Promise<void>;
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

export function ItemCard({ item, onUpdate, onDelete }: ItemCardProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [draftName, setDraftName] = useState(item.name);
  const [isBusy, setIsBusy] = useState(false);

  const daysLeft = daysUntil(item.estimated_freshness_date);
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

      <p className={`text-sm font-medium ${URGENCY_TEXT[urgency]}`}>{formatDaysLeft(daysLeft)}</p>

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
              onClick={() => runAction(() => onUpdate({ state: "CONSUMED" }))}
              className="rounded-md border border-slate-300 px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              Tükettim
            </button>
            <button
              type="button"
              disabled={isBusy}
              onClick={() => runAction(() => onUpdate({ state: "DISCARDED" }))}
              className="rounded-md border border-slate-300 px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              Attım
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
    </li>
  );
}
