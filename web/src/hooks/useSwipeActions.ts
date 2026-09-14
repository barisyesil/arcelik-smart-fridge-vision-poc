import { useCallback, useRef, useState } from "react";
import { postItemAction, undoAction, type ApiConfig } from "../api/client";
import type { DiscardReason, SwipeActionResponse, SwipeActionType } from "../api/types";

const UNDO_WINDOW_MS = 8_000; // SRS BR-007: sağ/sol swipe ~8 sn geri alınabilir.

export interface PendingUndo {
  actionId: string;
  itemName: string;
}

/**
 * Swipe aksiyonlarını (tükettim/attım/kontrol) idempotent biçimde gönderir ve
 * BR-007'deki 8 saniyelik "Geri Al" penceresini yönetir. Envanter/kuyruk/liste
 * yenilemesi çağıran tarafın işidir — bu hook yalnızca aksiyonun kendisini bilir.
 */
export function useSwipeActions(config: ApiConfig) {
  const [pendingUndo, setPendingUndo] = useState<PendingUndo | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearPending = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    setPendingUndo(null);
  }, []);

  const swipe = useCallback(
    async (
      itemId: string,
      itemName: string,
      type: SwipeActionType,
      discardReason?: DiscardReason,
    ): Promise<SwipeActionResponse> => {
      // client_action_id: her kullanıcı eylemi için yeni ve benzersiz — sunucu
      // tarafında idempotency anahtarıdır. Ağ tekrarı aynı sonucu üretir.
      const clientActionId = crypto.randomUUID();
      const result = await postItemAction(config, itemId, {
        client_action_id: clientActionId,
        type,
        discard_reason: discardReason,
      });

      if (type === "CONSUMED" || type === "DISCARDED") {
        clearPending();
        timerRef.current = setTimeout(clearPending, UNDO_WINDOW_MS);
        setPendingUndo({ actionId: result.action.action_id, itemName });
      }
      return result;
    },
    [config, clearPending],
  );

  const undo = useCallback(async () => {
    if (!pendingUndo) return;
    const { actionId } = pendingUndo;
    clearPending();
    await undoAction(config, actionId);
  }, [config, pendingUndo, clearPending]);

  return { swipe, undo, pendingUndo, dismissUndo: clearPending };
}
