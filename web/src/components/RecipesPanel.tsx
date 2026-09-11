import type { RecipeRecommendationDto } from "../api/types";

interface RecipesPanelProps {
  recommendations: RecipeRecommendationDto[];
  datasetVersion: string | null;
  isLoading: boolean;
  error: string | null;
}

/** SRS 8.11 — sabit, sürümlü veri setinden deterministik tarif önerisi. */
export function RecipesPanel({ recommendations, datasetVersion, isLoading, error }: RecipesPanelProps) {
  if (error) {
    return (
      <p className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/40 dark:bg-rose-950/20 dark:text-rose-300">
        {error}
      </p>
    );
  }

  if (isLoading && recommendations.length === 0) {
    return <p className="px-1 text-sm text-slate-400">Tarifler yükleniyor…</p>;
  }

  if (recommendations.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 px-6 py-10 text-center text-sm text-slate-400 dark:border-slate-700">
        Envanterine uyan tarif bulunamadı.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {datasetVersion && (
        <p className="text-[11px] text-slate-400">Tarif veri seti: {datasetVersion}</p>
      )}
      <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {recommendations.map((r) => (
          <li
            key={r.recipe_id}
            className="flex flex-col gap-2 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"
          >
            <div className="flex items-start justify-between gap-2">
              <p className="font-medium text-slate-900 dark:text-white">{r.title}</p>
              <span className="shrink-0 rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">
                %{r.match_score} uyum
              </span>
            </div>
            {r.description && (
              <p className="text-xs text-slate-500 dark:text-slate-400">{r.description}</p>
            )}
            <p className="text-[11px] text-slate-400">
              {r.prep_minutes != null && `Hazırlık ${r.prep_minutes} dk`}
              {r.cook_minutes != null && ` · Pişirme ${r.cook_minutes} dk`}
              {r.servings != null && ` · ${r.servings} porsiyon`}
            </p>
            {r.expiring_used_count > 0 && (
              <p className="text-[11px] text-amber-600 dark:text-amber-400">
                {r.expiring_used_count} yaklaşan ürünü değerlendiriyor
              </p>
            )}
            {r.missing_required.length > 0 && (
              <p className="text-[11px] text-slate-400">
                Eksik: {r.missing_required.join(", ")}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
