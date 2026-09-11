import { useId, useState } from "react";

interface ProfileSetupProps {
  onRegister: (displayName: string, fridgeId: string) => Promise<void>;
  isRegistering: boolean;
  registerError: string | null;
}

/**
 * Mobil SRS'teki kayıt konsepti: kullanıcı Ad-Soyad + önceden provision
 * edilmiş bir buzdolabı ID'si girer. Backend bu ID'yi registry'de doğrular;
 * geçersizse `invalid_fridge_id` döner (bkz. `useProfile.ts`).
 */
export function ProfileSetup({ onRegister, isRegistering, registerError }: ProfileSetupProps) {
  const [displayName, setDisplayName] = useState("");
  const [fridgeId, setFridgeId] = useState("");
  const nameId = useId();
  const fridgeIdInputId = useId();

  const canSubmit = displayName.trim().length > 0 && fridgeId.trim().length > 0 && !isRegistering;

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-4 px-4">
      <div className="flex flex-col gap-1 text-center">
        <h1 className="text-lg font-semibold text-slate-900 dark:text-white">Profilini oluştur</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Devam etmek için adını ve buzdolabının kimlik numarasını gir. Bu
          numara sana ayrıca iletildi (prototipte önceden tanımlı birkaç
          numaradan biri).
        </p>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!canSubmit) return;
          void onRegister(displayName.trim(), fridgeId.trim());
        }}
        className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"
      >
        <label htmlFor={nameId} className="flex flex-col gap-1 text-sm">
          <span className="text-slate-600 dark:text-slate-400">Ad Soyad</span>
          <input
            id={nameId}
            type="text"
            autoFocus
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Örn. Ayşe Yılmaz"
            className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm outline-none focus:border-slate-500 dark:border-slate-700 dark:bg-slate-950"
          />
        </label>

        <label htmlFor={fridgeIdInputId} className="flex flex-col gap-1 text-sm">
          <span className="text-slate-600 dark:text-slate-400">Buzdolabı ID</span>
          <input
            id={fridgeIdInputId}
            type="text"
            value={fridgeId}
            onChange={(e) => setFridgeId(e.target.value.toUpperCase())}
            placeholder="ARC-FRIDGE-001"
            className="rounded-md border border-slate-300 px-2.5 py-1.5 font-mono text-sm outline-none focus:border-slate-500 dark:border-slate-700 dark:bg-slate-950"
          />
        </label>

        {registerError && (
          <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-900/40 dark:bg-rose-950/20 dark:text-rose-300">
            {registerError}
          </p>
        )}

        <button
          type="submit"
          disabled={!canSubmit}
          className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-40 dark:bg-white dark:text-slate-900"
        >
          {isRegistering ? "Kaydediliyor…" : "Devam Et"}
        </button>
      </form>
    </div>
  );
}
