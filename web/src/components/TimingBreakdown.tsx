import type { UploadTicket } from "../hooks/useUpload";

/**
 * Fotoğraf yüklendiği andan ürünler hazır olana kadar geçen TOPLAM sürenin
 * neye bağlı olduğunu gösterir — darboğaz analizi için. İki kaynak birleşir:
 * istemci ölçümü (küçültme + S3'e yükleme, uçtan uca) ve backend'in ölçtüğü
 * aşamalar (`timings`: kuyruk, S3 indirme, Gemini, ayrıştırma).
 */

const BACKEND_LABELS: Record<string, string> = {
  queue_ms: "S3'e iniş → Lambda (kuyruk + soğuk başlatma)",
  s3_fetch_ms: "Kaynağı S3'ten indir",
  gemini_ms: "Gemini çağrısı (model)",
  parse_build_ms: "Ayrıştır + raf ömrü + item",
  commit_ms: "DynamoDB yazımı",
  lambda_ms: "Lambda toplam",
};

function Bar({ label, ms, total, tone }: { label: string; ms: number; total: number; tone: string }) {
  const pct = total > 0 ? Math.min(100, (ms / total) * 100) : 0;
  return (
    <div className="flex items-center gap-2">
      <span className="w-56 shrink-0 truncate text-[11px] text-slate-600 dark:text-slate-300">
        {label}
      </span>
      <div className="h-3 flex-1 overflow-hidden rounded bg-slate-100 dark:bg-slate-800">
        <div className={`h-full ${tone}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-16 shrink-0 text-right font-mono text-[11px] text-slate-500 dark:text-slate-400">
        {ms} ms
      </span>
    </div>
  );
}

export function TimingBreakdown({ ticket }: { ticket: UploadTicket }) {
  const t = ticket.timings;
  const clientUploadMs =
    ticket.uploadedAt && ticket.startedAt ? ticket.uploadedAt - ticket.startedAt : null;
  const totalMs =
    ticket.completedAt && ticket.startedAt ? ticket.completedAt - ticket.startedAt : null;

  if (!t && clientUploadMs == null) return null;

  const backendSum = t ? Object.values(t).reduce((a, b) => a + b, 0) : 0;
  // "Diğer": toplamdan istemci yükleme + ölçülen backend aşamalarını çıkar —
  // S3 event tetikleme gecikmesi, polling aralığı (~2 sn'ye kadar) ve DB yazımı.
  const otherMs =
    totalMs != null && clientUploadMs != null ? Math.max(0, totalMs - clientUploadMs - backendSum) : null;

  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-medium text-slate-600 dark:text-slate-300">
          Yanıt süresi dökümü
        </h4>
        {totalMs != null && (
          <span className="font-mono text-xs font-semibold text-slate-900 dark:text-white">
            toplam {totalMs} ms
          </span>
        )}
      </div>

      {clientUploadMs != null && totalMs != null && (
        <Bar
          label="Küçült + S3'e yükle (istemci)"
          ms={clientUploadMs}
          total={totalMs}
          tone="bg-sky-400"
        />
      )}
      {t &&
        Object.entries(t).map(([key, ms]) => (
          <Bar
            key={key}
            label={BACKEND_LABELS[key] ?? key}
            ms={ms}
            total={totalMs ?? backendSum}
            tone={key === "gemini_ms" ? "bg-amber-400" : "bg-emerald-400"}
          />
        ))}
      {otherMs != null && totalMs != null && (
        <Bar
          label="Diğer (S3 olay gecikmesi + polling + DB)"
          ms={otherMs}
          total={totalMs}
          tone="bg-slate-300 dark:bg-slate-600"
        />
      )}

      <p className="mt-1 text-[10px] text-slate-400">
        Backend aşamaları extractor'ın ölçümüdür (CloudWatch log'unda da var:{" "}
        <code>event: extraction_completed</code>). Gemini genelde en büyük paydır.
      </p>
    </div>
  );
}
