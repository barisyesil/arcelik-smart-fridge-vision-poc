import { useCallback, useEffect, useState } from "react";
import { deleteItem, listItems, patchItem, type ApiConfig } from "../api/client";
import type { InventoryItemDto, ItemPatch } from "../api/types";

interface UseInventoryResult {
  items: InventoryItemDto[];
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  update: (itemId: string, patch: ItemPatch) => Promise<void>;
  remove: (itemId: string) => Promise<void>;
}

export function useInventory(config: ApiConfig, enabled: boolean): UseInventoryResult {
  const [items, setItems] = useState<InventoryItemDto[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    setIsLoading(true);
    setError(null);
    try {
      const response = await listItems(config);
      setItems(response.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Envanter alınamadı");
    } finally {
      setIsLoading(false);
    }
  }, [config, enabled]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const update = useCallback(
    async (itemId: string, patch: ItemPatch) => {
      const updated = await patchItem(config, itemId, patch);
      setItems((prev) => {
        // ACTIVE dışına çıkan kalem GSI1'den düştüğü gibi buradan da düşer —
        // arayüz backend'in sparse index davranışını taklit eder.
        if (updated.state !== "ACTIVE") {
          return prev.filter((item) => item.item_id !== itemId);
        }
        return prev.map((item) => (item.item_id === itemId ? updated : item));
      });
    },
    [config],
  );

  const remove = useCallback(
    async (itemId: string) => {
      await deleteItem(config, itemId);
      setItems((prev) => prev.filter((item) => item.item_id !== itemId));
    },
    [config],
  );

  return { items, isLoading, error, refresh, update, remove };
}
