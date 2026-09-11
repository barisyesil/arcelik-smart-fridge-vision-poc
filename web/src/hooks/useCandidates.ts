import { useCallback, useEffect, useState } from "react";
import { acceptCandidate, dismissCandidate, getCandidates, type ApiConfig } from "../api/client";
import type { ReplacementCandidateDto } from "../api/types";

/** Bekleyen (PENDING) yeniden alma önerileri — SRS 8.10. */
export function useCandidates(config: ApiConfig, enabled: boolean) {
  const [candidates, setCandidates] = useState<ReplacementCandidateDto[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    setIsLoading(true);
    setError(null);
    try {
      const response = await getCandidates(config, "PENDING");
      setCandidates(response.candidates);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Öneriler alınamadı");
    } finally {
      setIsLoading(false);
    }
  }, [config, enabled]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const accept = useCallback(
    async (candidateId: string) => {
      await acceptCandidate(config, candidateId);
      await refresh();
    },
    [config, refresh],
  );

  const dismiss = useCallback(
    async (candidateId: string) => {
      await dismissCandidate(config, candidateId);
      await refresh();
    },
    [config, refresh],
  );

  return { candidates, isLoading, error, refresh, accept, dismiss };
}
