import { useCallback, useEffect, useState } from "react";
import { getReviewQueue, type ApiConfig } from "../api/client";
import type { ReviewQueueEntryDto } from "../api/types";

export function useReviewQueue(config: ApiConfig, enabled: boolean) {
  const [queue, setQueue] = useState<ReviewQueueEntryDto[]>([]);
  const [totalPending, setTotalPending] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    setIsLoading(true);
    setError(null);
    try {
      const response = await getReviewQueue(config);
      setQueue(response.queue);
      setTotalPending(response.total_pending);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Kontrol kuyruğu alınamadı");
    } finally {
      setIsLoading(false);
    }
  }, [config, enabled]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { queue, totalPending, isLoading, error, refresh };
}
