import { useId, useState } from "react";
import type { DeploySettings } from "../hooks/useSettings";

interface SettingsBarProps {
  config: DeploySettings;
  onChange: (next: Partial<DeploySettings>) => void;
}

/**
 * Bu deploy'a özel bağlantı bilgileri: API adresi ve Cognito Hosted UI
 * domain/client ID'si (CDK çıktıları `ApiUrl`, `CognitoDomain`,
 * `WebTestClientId`). Kimlik doğrulama burada değil, `useAuth`/Cognito'da olur.
 */
export function SettingsBar({ config, onChange }: SettingsBarProps) {
  const [isOpen, setIsOpen] = useState(!config.baseUrl || !config.cognitoDomain);
  const urlId = useId();
  const domainId = useId();
  const clientId = useId();

  return (
    <div className="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-sm font-medium text-slate-700 dark:text-slate-200"
      >
        <span className="shrink-0">Bağlantı ayarları</span>
        <span className="min-w-0 truncate text-slate-400">
          {config.baseUrl ? new URL(config.baseUrl || "http://-").host || config.baseUrl : "yapılandırılmadı"}
        </span>
      </button>

      {isOpen && (
        <div className="grid gap-3 border-t border-slate-100 px-4 py-3 sm:grid-cols-2 dark:border-slate-800">
          <label htmlFor={urlId} className="flex flex-col gap-1 text-sm sm:col-span-2">
            <span className="text-slate-600 dark:text-slate-400">API adresi (CDK çıktısı: ApiUrl)</span>
            <input
              id={urlId}
              type="url"
              placeholder="https://xxxx.execute-api.eu-central-1.amazonaws.com"
              value={config.baseUrl}
              onChange={(e) => onChange({ baseUrl: e.target.value })}
              className="rounded-md border border-slate-300 px-2.5 py-1.5 font-mono text-xs outline-none focus:border-slate-500 dark:border-slate-700 dark:bg-slate-950"
            />
          </label>
          <label htmlFor={domainId} className="flex flex-col gap-1 text-sm">
            <span className="text-slate-600 dark:text-slate-400">Cognito domain (CognitoDomain)</span>
            <input
              id={domainId}
              type="url"
              placeholder="https://fridge-123456789012.auth.eu-central-1.amazoncognito.com"
              value={config.cognitoDomain}
              onChange={(e) => onChange({ cognitoDomain: e.target.value })}
              className="rounded-md border border-slate-300 px-2.5 py-1.5 font-mono text-xs outline-none focus:border-slate-500 dark:border-slate-700 dark:bg-slate-950"
            />
          </label>
          <label htmlFor={clientId} className="flex flex-col gap-1 text-sm">
            <span className="text-slate-600 dark:text-slate-400">Cognito client ID (WebTestClientId)</span>
            <input
              id={clientId}
              type="text"
              value={config.cognitoClientId}
              onChange={(e) => onChange({ cognitoClientId: e.target.value })}
              className="rounded-md border border-slate-300 px-2.5 py-1.5 font-mono text-xs outline-none focus:border-slate-500 dark:border-slate-700 dark:bg-slate-950"
            />
          </label>
        </div>
      )}
    </div>
  );
}
