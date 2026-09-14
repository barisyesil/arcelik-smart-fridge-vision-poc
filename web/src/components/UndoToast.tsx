import type { PendingUndo } from "../hooks/useSwipeActions";

interface UndoToastProps {
  pending: PendingUndo;
  onUndo: () => void;
}

/** BR-007: sağ/sol swipe ~8 sn geri alınabilir. */
export function UndoToast({ pending, onUndo }: UndoToastProps) {
  return (
    <div className="fixed inset-x-0 bottom-4 z-40 flex justify-center px-4">
      <div className="flex items-center gap-3 rounded-full bg-slate-900 px-4 py-2 text-sm text-white shadow-lg dark:bg-white dark:text-slate-900">
        <span className="truncate">{pending.itemName} güncellendi</span>
        <button
          type="button"
          onClick={onUndo}
          className="shrink-0 font-medium underline underline-offset-2"
        >
          Geri Al
        </button>
      </div>
    </div>
  );
}
