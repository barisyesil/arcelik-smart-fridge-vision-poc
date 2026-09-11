import { useCallback, useEffect, useState } from "react";
import {
  deleteShoppingItem,
  getShoppingList,
  patchShoppingItem,
  postShoppingItem,
  type ApiConfig,
} from "../api/client";
import type { ShoppingItemCreate, ShoppingItemPatch, ShoppingListItemDto } from "../api/types";

export function useShopping(config: ApiConfig, enabled: boolean) {
  const [active, setActive] = useState<ShoppingListItemDto[]>([]);
  const [completed, setCompleted] = useState<ShoppingListItemDto[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    setIsLoading(true);
    setError(null);
    try {
      const response = await getShoppingList(config);
      setActive(response.active);
      setCompleted(response.completed);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Alışveriş listesi alınamadı");
    } finally {
      setIsLoading(false);
    }
  }, [config, enabled]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const add = useCallback(
    async (item: ShoppingItemCreate) => {
      await postShoppingItem(config, item);
      await refresh();
    },
    [config, refresh],
  );

  const update = useCallback(
    async (shoppingItemId: string, patch: ShoppingItemPatch) => {
      await patchShoppingItem(config, shoppingItemId, patch);
      await refresh();
    },
    [config, refresh],
  );

  const remove = useCallback(
    async (shoppingItemId: string) => {
      await deleteShoppingItem(config, shoppingItemId);
      await refresh();
    },
    [config, refresh],
  );

  return { active, completed, isLoading, error, refresh, add, update, remove };
}
