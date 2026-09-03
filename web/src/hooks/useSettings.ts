import { useCallback, useEffect, useState } from "react";
import type { ApiConfig } from "../api/client";

const STORAGE_KEY = "fridge.settings.v1";

const DEFAULTS: ApiConfig = {
  baseUrl: import.meta.env.VITE_API_URL ?? "",
  userId: "u_demo",
};

function load(): ApiConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULTS;
    const parsed = JSON.parse(raw) as Partial<ApiConfig>;
    return { ...DEFAULTS, ...parsed };
  } catch {
    return DEFAULTS;
  }
}

/**
 * API adresi ve `x-user-id` tarayıcıda saklanır — Faz 1'de kimlik doğrulama
 * yok, bu yüzden bu ayar bir "hangi kullanıcı gibi davranayım" anahtarıdır,
 * gerçek bir kimlik değildir.
 */
export function useSettings() {
  const [config, setConfigState] = useState<ApiConfig>(load);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
    } catch {
      // Gizli sekme / depolama kapalı: sessizce yok say, bir sonraki
      // oturumda varsayılana döner.
    }
  }, [config]);

  const setConfig = useCallback((next: Partial<ApiConfig>) => {
    setConfigState((prev) => ({ ...prev, ...next }));
  }, []);

  const isConfigured = config.baseUrl.trim().length > 0;

  return { config, setConfig, isConfigured };
}
