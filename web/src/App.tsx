import { useCallback } from "react";
import { Disclaimer } from "./components/Disclaimer";
import { InventoryList } from "./components/InventoryList";
import { SettingsBar } from "./components/SettingsBar";
import { UploadPanel } from "./components/UploadPanel";
import { useInventory } from "./hooks/useInventory";
import { useSettings } from "./hooks/useSettings";
import { useUpload } from "./hooks/useUpload";

export default function App() {
  const { config, setConfig, isConfigured } = useSettings();
  const inventory = useInventory(config, isConfigured);
  const { tickets, startUpload } = useUpload(config);

  const handleFileSelected = useCallback(
    (file: File) => {
      void startUpload(file, () => {
        void inventory.refresh();
      });
    },
    [startUpload, inventory],
  );

  return (
    <div className="mx-auto flex min-h-screen max-w-5xl flex-col gap-6 px-4 py-8 sm:px-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold text-slate-900 dark:text-white">
          Akıllı Buzdolabı — Test Arayüzü
        </h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Faz 1 PoC · fotoğraf yükle, çıkarımı doğrula, envanteri düzelt
        </p>
      </header>

      <SettingsBar config={config} onChange={setConfig} />

      {!isConfigured ? (
        <div className="rounded-xl border border-dashed border-slate-300 px-6 py-10 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
          Devam etmeden önce yukarıdan API adresini girin.
        </div>
      ) : (
        <>
          <Disclaimer />

          <section className="flex flex-col gap-3">
            <h2 className="text-sm font-medium text-slate-700 dark:text-slate-200">
              Fotoğraf yükle
            </h2>
            <UploadPanel tickets={tickets} onFileSelected={handleFileSelected} disabled={false} />
          </section>

          <section className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-medium text-slate-700 dark:text-slate-200">Envanter</h2>
              <button
                type="button"
                onClick={() => void inventory.refresh()}
                className="text-xs text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
              >
                Yenile
              </button>
            </div>
            <InventoryList
              items={inventory.items}
              isLoading={inventory.isLoading}
              error={inventory.error}
              onUpdate={inventory.update}
              onDelete={inventory.remove}
            />
          </section>
        </>
      )}
    </div>
  );
}
