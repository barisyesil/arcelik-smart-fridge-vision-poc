import { useId, useState } from "react";
import type { ReplacementCandidateDto, ShoppingListItemDto } from "../api/types";
import { categoryLabel } from "../lib/labels";

interface ShoppingPanelProps {
  candidates: ReplacementCandidateDto[];
  active: ShoppingListItemDto[];
  completed: ShoppingListItemDto[];
  isLoading: boolean;
  error: string | null;
  onAcceptCandidate: (candidateId: string) => Promise<void>;
  onDismissCandidate: (candidateId: string) => Promise<void>;
  onAddItem: (name: string) => Promise<void>;
  onComplete: (shoppingItemId: string) => Promise<void>;
  onRemove: (shoppingItemId: string) => Promise<void>;
}

/**
 * SRS 8.10 — iki veri grubu bilinçli olarak ayrı gösterilir: bekleyen
 * öneriler (swipe'tan doğan, henüz onaylanmamış) ve aktif alışveriş listesi.
 * Bir öneri kullanıcı onayı olmadan aktif listeye eklenmez (BR-010).
 */
export function ShoppingPanel({
  candidates,
  active,
  completed,
  isLoading,
  error,
  onAcceptCandidate,
  onDismissCandidate,
  onAddItem,
  onComplete,
  onRemove,
}: ShoppingPanelProps) {
  const [draft, setDraft] = useState("");
  const inputId = useId();

  if (error) {
    return (
      <p className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/40 dark:bg-rose-950/20 dark:text-rose-300">
        {error}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      {candidates.length > 0 && (
        <section className="flex flex-col gap-2">
          <h3 className="text-xs font-medium text-slate-500 dark:text-slate-400">
            Yeniden alma önerileri
          </h3>
          <ul className="flex flex-col gap-1.5">
            {candidates.map((c) => (
              <li
                key={c.candidate_id}
                className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-800 dark:bg-slate-900"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium text-slate-800 dark:text-slate-100">{c.name}</p>
                  <p className="text-[11px] text-slate-400">
                    {categoryLabel(c.category)} ·{" "}
                    {c.reason === "CONSUMED" ? "tüketildi" : "kullanılamadı"}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void onAcceptCandidate(c.candidate_id)}
                  className="shrink-0 rounded-md border border-emerald-300 px-2.5 py-1 text-xs text-emerald-700 hover:bg-emerald-50 dark:border-emerald-800 dark:text-emerald-300 dark:hover:bg-emerald-950/30"
                >
                  Listeye ekle
                </button>
                <button
                  type="button"
                  onClick={() => void onDismissCandidate(c.candidate_id)}
                  className="shrink-0 rounded-md px-2 py-1 text-xs text-slate-400 hover:text-slate-600"
                >
                  Geç
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="flex flex-col gap-2">
        <h3 className="text-xs font-medium text-slate-500 dark:text-slate-400">
          Aktif alışveriş listesi
        </h3>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const name = draft.trim();
            if (!name) return;
            void onAddItem(name).then(() => setDraft(""));
          }}
          className="flex gap-2"
        >
          <label htmlFor={inputId} className="sr-only">
            Yeni ürün
          </label>
          <input
            id={inputId}
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Ürün ekle…"
            className="flex-1 rounded-md border border-slate-300 px-2.5 py-1.5 text-sm outline-none focus:border-slate-500 dark:border-slate-700 dark:bg-slate-950"
          />
          <button
            type="submit"
            disabled={draft.trim().length === 0}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40 dark:bg-white dark:text-slate-900"
          >
            Ekle
          </button>
        </form>

        {isLoading && active.length === 0 ? (
          <p className="px-1 text-sm text-slate-400">Yükleniyor…</p>
        ) : active.length === 0 ? (
          <p className="rounded-lg border border-dashed border-slate-300 px-4 py-6 text-center text-sm text-slate-400 dark:border-slate-700">
            Listen henüz boş.
          </p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {active.map((item) => (
              <li
                key={item.shopping_item_id}
                className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-800 dark:bg-slate-900"
              >
                <span className="min-w-0 flex-1 truncate text-slate-800 dark:text-slate-100">
                  {item.name}
                </span>
                <button
                  type="button"
                  onClick={() => void onComplete(item.shopping_item_id)}
                  className="shrink-0 rounded-md border border-slate-300 px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  Tamamlandı
                </button>
                <button
                  type="button"
                  onClick={() => void onRemove(item.shopping_item_id)}
                  className="shrink-0 rounded-md px-2 py-1 text-xs text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-950/30"
                >
                  Sil
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {completed.length > 0 && (
        <section className="flex flex-col gap-2">
          <h3 className="text-xs font-medium text-slate-500 dark:text-slate-400">Tamamlananlar</h3>
          <ul className="flex flex-wrap gap-1.5">
            {completed.map((item) => (
              <li
                key={item.shopping_item_id}
                className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-500 line-through dark:bg-slate-800 dark:text-slate-400"
              >
                {item.name}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
