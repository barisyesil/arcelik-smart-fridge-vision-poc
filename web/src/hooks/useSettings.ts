import { useCallback, useEffect, useState } from "react";

export interface DeploySettings {
  baseUrl: string;
  /** Cognito Hosted UI taban URL'si, örn. https://fridge-123.auth.eu-central-1.amazoncognito.com */
  cognitoDomain: string;
  /** Web test client ID (CDK çıktısı `WebTestClientId`). */
  cognitoClientId: string;
}

const STORAGE_KEY = "fridge.settings.v2";

const DEFAULTS: DeploySettings = {
  baseUrl: import.meta.env.VITE_API_URL ?? "",
  cognitoDomain: import.meta.env.VITE_COGNITO_DOMAIN ?? "",
  cognitoClientId: import.meta.env.VITE_COGNITO_CLIENT_ID ?? "",
};

function load(): DeploySettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULTS;
    const parsed = JSON.parse(raw) as Partial<DeploySettings>;
    return { ...DEFAULTS, ...parsed };
  } catch {
    return DEFAULTS;
  }
}

/**
 * Bu deploy'a özel bağlantı bilgileri (API adresi + Cognito domain/client)
 * tarayıcıda saklanır. Kimlik doğrulama Cognito'da olur (bkz. `useAuth`); bu
 * ayarlar yalnızca "hangi backend'e/hangi kullanıcı havuzuna bağlanayım"
 * sorusunu cevaplar, bir kimlik değildir.
 */
export function useSettings() {
  const [config, setConfigState] = useState<DeploySettings>(load);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
    } catch {
      // Gizli sekme / depolama kapalı: sessizce yok say.
    }
  }, [config]);

  const setConfig = useCallback((next: Partial<DeploySettings>) => {
    setConfigState((prev) => ({ ...prev, ...next }));
  }, []);

  const isConfigured =
    config.baseUrl.trim().length > 0 &&
    config.cognitoDomain.trim().length > 0 &&
    config.cognitoClientId.trim().length > 0;

  return { config, setConfig, isConfigured };
}
