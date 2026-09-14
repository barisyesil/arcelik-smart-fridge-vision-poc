import { useCallback, useEffect, useState } from "react";
import { getRecipes, type ApiConfig } from "../api/client";
import type { RecipeRecommendationDto } from "../api/types";

export function useRecipes(config: ApiConfig, enabled: boolean) {
  const [recommendations, setRecommendations] = useState<RecipeRecommendationDto[]>([]);
  const [datasetVersion, setDatasetVersion] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    setIsLoading(true);
    setError(null);
    try {
      const response = await getRecipes(config);
      setRecommendations(response.recommendations);
      setDatasetVersion(response.dataset_version);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Tarif önerileri alınamadı");
    } finally {
      setIsLoading(false);
    }
  }, [config, enabled]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { recommendations, datasetVersion, isLoading, error, refresh };
}
