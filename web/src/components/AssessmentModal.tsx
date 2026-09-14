import { useState } from "react";
import type {
  FreshnessAssessmentReason,
  FreshnessAssessmentRequest,
  InventoryItemDto,
  ObservedFreshnessState,
} from "../api/types";

interface AssessmentModalProps {
  item: InventoryItemDto;
  onSubmit: (payload: FreshnessAssessmentRequest) => Promise<void>;
  onClose: () => void;
}

const OBSERVED_OPTIONS: { value: ObservedFreshnessState; label: string }[] = [
  { value: "STILL_FRESH", label: "Hâlâ taze" },
  { value: "BORDERLINE", label: "Sınırda" },
  { value: "SPOILED", label: "Bozulmuş" },
  { value: "UNSURE", label: "Emin değilim" },
];

const DAYS_OPTIONS: { label: string; days: number }[] = [
  { label: "1 gün", days: 1 },
  { label: "3 gün", days: 3 },
  { label: "5 gün", days: 5 },
  { label: "1 hafta", days: 7 },
];

const REVIEW_OPTIONS: { label: string; hoursFromNow: number }[] = [
  { label: "Yarın", hoursFromNow: 24 },
  { label: "3 gün sonra", hoursFromNow: 72 },
  { label: "1 hafta sonra", hoursFromNow: 168 },
];

const REASON_OPTIONS: { value: FreshnessAssessmentReason; label: string }[] = [
  { value: "LOOKS_FRESH", label: "Görünüşü iyi" },
  { value: "TEXTURE_CHANGED", label: "Doku değişti" },
  { value: "SMELL_CHANGED", label: "Koku değişti" },
  { value: "PACKAGE_DAMAGED", label: "Ambalaj hasarlı" },
  { value: "OPENED_TODAY", label: "Bugün açıldı" },
  { value: "WRONG_DETECTION", label: "Ürün yanlış tanındı" },
];

/**
 * Yukarı-swipe değerlendirme paneli (SRS 8.8). Üç ayrı kavramı bilinçli
 * olarak ayrı tutar: mevcut durum (zorunlu), kalan gün tahmini (isteğe
 * bağlı), yeniden kontrol zamanı (isteğe bağlı). Kullanıcı rastgele cevap
 * vermeye zorlanmaz — hiçbiri zorunlu değil, yalnızca `observed_state` hariç.
 */
export function AssessmentModal({ item, onSubmit, onClose }: AssessmentModalProps) {
  const [observedState, setObservedState] = useState<ObservedFreshnessState | null>(null);
  const [daysRemaining, setDaysRemaining] = useState<number | null>(null);
  const [reviewHours, setReviewHours] = useState<number | null>(null);
  const [reason, setReason] = useState<FreshnessAssessmentReason | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = observedState !== null && !isSubmitting;

  const handleSubmit = async () => {
    if (!observedState) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const payload: FreshnessAssessmentRequest = { observed_state: observedState };
      if (daysRemaining !== null) {
        payload.user_estimated_days_remaining = daysRemaining;
        const target = new Date();
        target.setDate(target.getDate() + daysRemaining);
        payload.user_estimated_fresh_until = target.toISOString().slice(0, 10);
      }
      if (reviewHours !== null) {
        const next = new Date();
        next.setHours(next.getHours() + reviewHours);
        payload.next_review_at = next.toISOString();
      }
      if (reason) payload.reason = reason;
      await onSubmit(payload);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Değerlendirme kaydedilemedi");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center">
      <div className="flex max-h-[90vh] w-full max-w-md flex-col gap-4 overflow-y-auto rounded-t-2xl bg-white p-5 sm:rounded-2xl dark:bg-slate-900">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h3 className="text-sm font-semibold text-slate-900 dark:text-white">{item.name}</h3>
            <p className="text-xs text-slate-400">
              Sistem tahmini: {item.predicted_fresh_until} — bu tahmin bu değerlendirmeyle
              DEĞİŞTİRİLMEZ, senin gözlemin ayrıca saklanır.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-md px-2 py-1 text-xs text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            Kapat
          </button>
        </div>

        <section className="flex flex-col gap-1.5">
          <p className="text-xs font-medium text-slate-600 dark:text-slate-300">Mevcut durum</p>
          <div className="flex flex-wrap gap-1.5">
            {OBSERVED_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setObservedState(opt.value)}
                className={`rounded-full border px-3 py-1 text-xs ${
                  observedState === opt.value
                    ? "border-slate-900 bg-slate-900 text-white dark:border-white dark:bg-white dark:text-slate-900"
                    : "border-slate-300 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </section>

        <section className="flex flex-col gap-1.5">
          <p className="text-xs font-medium text-slate-600 dark:text-slate-300">
            Kalan süre tahminin (isteğe bağlı)
          </p>
          <div className="flex flex-wrap gap-1.5">
            {DAYS_OPTIONS.map((opt) => (
              <button
                key={opt.days}
                type="button"
                onClick={() => setDaysRemaining(daysRemaining === opt.days ? null : opt.days)}
                className={`rounded-full border px-3 py-1 text-xs ${
                  daysRemaining === opt.days
                    ? "border-slate-900 bg-slate-900 text-white dark:border-white dark:bg-white dark:text-slate-900"
                    : "border-slate-300 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </section>

        <section className="flex flex-col gap-1.5">
          <p className="text-xs font-medium text-slate-600 dark:text-slate-300">
            Yeniden kontrol zamanı (isteğe bağlı)
          </p>
          <div className="flex flex-wrap gap-1.5">
            {REVIEW_OPTIONS.map((opt) => (
              <button
                key={opt.hoursFromNow}
                type="button"
                onClick={() =>
                  setReviewHours(reviewHours === opt.hoursFromNow ? null : opt.hoursFromNow)
                }
                className={`rounded-full border px-3 py-1 text-xs ${
                  reviewHours === opt.hoursFromNow
                    ? "border-slate-900 bg-slate-900 text-white dark:border-white dark:bg-white dark:text-slate-900"
                    : "border-slate-300 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </section>

        <section className="flex flex-col gap-1.5">
          <p className="text-xs font-medium text-slate-600 dark:text-slate-300">
            Neden (isteğe bağlı)
          </p>
          <div className="flex flex-wrap gap-1.5">
            {REASON_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setReason(reason === opt.value ? null : opt.value)}
                className={`rounded-full border px-3 py-1 text-xs ${
                  reason === opt.value
                    ? "border-slate-900 bg-slate-900 text-white dark:border-white dark:bg-white dark:text-slate-900"
                    : "border-slate-300 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </section>

        {error && (
          <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-900/40 dark:bg-rose-950/20 dark:text-rose-300">
            {error}
          </p>
        )}

        <button
          type="button"
          disabled={!canSubmit}
          onClick={() => void handleSubmit()}
          className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-40 dark:bg-white dark:text-slate-900"
        >
          {isSubmitting ? "Kaydediliyor…" : "Değerlendirmeyi Kaydet"}
        </button>
      </div>
    </div>
  );
}
