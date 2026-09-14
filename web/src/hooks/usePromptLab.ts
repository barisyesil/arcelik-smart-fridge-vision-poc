import { useCallback, useEffect, useState } from "react";
import {
  deletePrompt,
  fetchMeta,
  fetchPrompts,
  runExtract,
  savePrompt,
  type ExtractResult,
  type LabMeta,
  type PromptVersion,
} from "../api/playground";

const URL_KEY = "fridge.playground.url";
const DEFAULT_URL = import.meta.env.VITE_PLAYGROUND_URL ?? "http://localhost:8900";

function loadUrl(): string {
  try {
    return localStorage.getItem(URL_KEY) ?? DEFAULT_URL;
  } catch {
    return DEFAULT_URL;
  }
}

/**
 * Prompt Lab durumunu yönetir: yerel sunucu adresi, prompt sürümleri, seçili
 * sürüm + düzenleme tamponu, çalıştırma sonucu. Üretim hook'larından tamamen
 * bağımsız — yalnızca yerel `playground` sunucusuna konuşur.
 */
export function usePromptLab() {
  const [serverUrl, setServerUrlState] = useState<string>(loadUrl);
  const [meta, setMeta] = useState<LabMeta | null>(null);
  const [prompts, setPrompts] = useState<PromptVersion[]>([]);
  const [connError, setConnError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [result, setResult] = useState<ExtractResult | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const setServerUrl = useCallback((url: string) => {
    setServerUrlState(url);
    try {
      localStorage.setItem(URL_KEY, url);
    } catch {
      // depolama kapalı: yok say
    }
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setConnError(null);
    try {
      const [m, p] = await Promise.all([fetchMeta(serverUrl), fetchPrompts(serverUrl)]);
      setMeta(m);
      setPrompts(p);
    } catch (err) {
      setConnError(
        err instanceof Error
          ? `Sunucuya bağlanılamadı (${serverUrl}). Yerel Prompt Lab çalışıyor mu? — ${err.message}`
          : "Bilinmeyen bağlantı hatası",
      );
      setMeta(null);
      setPrompts([]);
    } finally {
      setLoading(false);
    }
  }, [serverUrl]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const run = useCallback(
    async (params: {
      image: File;
      promptId?: string;
      systemPrompt?: string;
      model: string;
      temperature: number;
    }) => {
      setRunning(true);
      setRunError(null);
      try {
        const res = await runExtract(serverUrl, params);
        setResult(res);
        return res;
      } catch (err) {
        setRunError(err instanceof Error ? err.message : "Çalıştırma başarısız");
        return null;
      } finally {
        setRunning(false);
      }
    },
    [serverUrl],
  );

  const save = useCallback(
    async (version: { id: string; label: string; description: string; system_prompt: string }) => {
      await savePrompt(serverUrl, version);
      await refresh();
    },
    [serverUrl, refresh],
  );

  const remove = useCallback(
    async (id: string) => {
      await deletePrompt(serverUrl, id);
      await refresh();
    },
    [serverUrl, refresh],
  );

  return {
    serverUrl,
    setServerUrl,
    meta,
    prompts,
    connError,
    loading,
    refresh,
    result,
    running,
    runError,
    run,
    save,
    remove,
  };
}
