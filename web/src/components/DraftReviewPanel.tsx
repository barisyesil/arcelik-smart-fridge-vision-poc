import { useEffect, useMemo, useState } from "react";
import { confirmUpload, createCropUpload, uploadToS3, type ApiConfig } from "../api/client";
import type { ConfirmItem } from "../api/types";
import type { UploadTicket } from "../hooks/useUpload";
import { buildCropStyle, loadImageSize } from "../lib/cropImage";
import { cropToBlob } from "../lib/cropToBlob";
import { categoryLabel, formatQuantity } from "../lib/labels";
import { TimingBreakdown } from "./TimingBreakdown";

interface Props {
  ticket: UploadTicket;
  apiConfig: ApiConfig;
  onConfirmed: () => void;
  onStateChange: (s: UploadTicket["confirmState"]) => void;
}

type CropStatus = "idle" | "uploading" | "done" | "error" | "nobox";

interface RowState {
  keep: boolean;
  name: string;
  cropStatus: CropStatus;
  cropKey: string | null;
}

const CROP_LABEL: Record<CropStatus, string> = {
  idle: "",
  uploading: "S3'e yükleniyor…",
  done: "S3'e yüklendi ✓",
  error: "crop yüklenemedi",
  nobox: "kutu yok — fotoğrafsız",
};

/**
 * Kontrol ekranı: extraction'ın bulduğu DRAFT ürünler burada gösterilir.
 * Kullanıcı hangilerini ekleyeceğini seçer (ve adını düzeltebilir), onaylar.
 * Onayda her tutulan ürünün kırpılmış görseli S3'e yüklenir (kalıcı) ve confirm
 * çağrısıyla ürün ACTIVE olur. Kullanıcı crop'ların S3'e gittiğini satır başına
 * görür; toplam yanıt süresi dökümü de gösterilir.
 */
export function DraftReviewPanel({ ticket, apiConfig, onConfirmed, onStateChange }: Props) {
  const [rows, setRows] = useState<Record<string, RowState>>({});
  const [imageSize, setImageSize] = useState<{ width: number; height: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Ürünler geldiğinde satır durumunu kur (varsayılan: hepsi tutulur).
  useEffect(() => {
    setRows((prev) => {
      const next: Record<string, RowState> = {};
      for (const item of ticket.items) {
        next[item.item_id] = prev[item.item_id] ?? {
          keep: true,
          name: item.name,
          cropStatus: "idle",
          cropKey: null,
        };
      }
      return next;
    });
  }, [ticket.items]);

  // Kırpma önizlemesi için yerel görselin doğal boyutu.
  useEffect(() => {
    if (!ticket.sourceObjectUrl) return;
    let alive = true;
    loadImageSize(ticket.sourceObjectUrl)
      .then((s) => alive && setImageSize(s))
      .catch(() => alive && setImageSize(null));
    return () => {
      alive = false;
    };
  }, [ticket.sourceObjectUrl]);

  const setRow = (itemId: string, patch: Partial<RowState>) =>
    setRows((prev) => ({ ...prev, [itemId]: { ...prev[itemId], ...patch } }));

  const keptCount = useMemo(() => Object.values(rows).filter((r) => r.keep).length, [rows]);
  const busy = ticket.confirmState === "CONFIRMING";
  const done = ticket.confirmState === "CONFIRMED";

  const handleConfirm = async () => {
    setError(null);
    onStateChange("CONFIRMING");
    const confirmed: ConfirmItem[] = [];
    try {
      for (const item of ticket.items) {
        const r = rows[item.item_id];
        if (!r?.keep) continue;

        let imageKey: string | undefined;
        if (item.bounding_box && ticket.sourceBlob) {
          setRow(item.item_id, { cropStatus: "uploading" });
          try {
            const blob = await cropToBlob(ticket.sourceBlob, item.bounding_box);
            const presign = await createCropUpload(apiConfig, ticket.uploadId);
            await uploadToS3(presign, blob, "image/jpeg");
            imageKey = presign.object_key;
            setRow(item.item_id, { cropStatus: "done", cropKey: imageKey });
            // eslint-disable-next-line no-console
            console.info("[crop→S3]", item.name, "→", imageKey);
          } catch (cropErr) {
            setRow(item.item_id, { cropStatus: "error" });
            // eslint-disable-next-line no-console
            console.warn("[crop→S3] başarısız", item.name, cropErr);
          }
        } else {
          setRow(item.item_id, { cropStatus: "nobox" });
        }

        const edit: ConfirmItem = { item_id: item.item_id };
        if (imageKey) edit.image_key = imageKey;
        if (r.name.trim() && r.name.trim() !== item.name) edit.name = r.name.trim();
        confirmed.push(edit);
      }

      await confirmUpload(apiConfig, ticket.uploadId, confirmed);
      onStateChange("CONFIRMED");
      onConfirmed();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Onay başarısız");
      onStateChange("PENDING_REVIEW");
    }
  };

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="truncate text-sm font-medium text-slate-700 dark:text-slate-200">
          {done ? "Envantere eklendi" : "Kontrol et ve onayla"} — {ticket.fileName}
        </h3>
        <span className="shrink-0 text-xs text-slate-400">{ticket.items.length} ürün bulundu</span>
      </div>

      <TimingBreakdown ticket={ticket} />

      {ticket.items.length === 0 && (
        <p className="text-sm text-slate-400">Bu fotoğrafta ürün bulunamadı.</p>
      )}

      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {ticket.items.map((item) => {
          const r = rows[item.item_id];
          if (!r) return null;
          const cropStyle =
            item.bounding_box && ticket.sourceObjectUrl && imageSize
              ? buildCropStyle(
                  ticket.sourceObjectUrl,
                  item.bounding_box,
                  imageSize.width,
                  imageSize.height,
                )
              : null;
          return (
            <li
              key={item.item_id}
              className={`flex gap-3 rounded-lg border p-2 ${
                r.keep
                  ? "border-slate-200 dark:border-slate-700"
                  : "border-slate-200 opacity-50 dark:border-slate-800"
              }`}
            >
              {cropStyle ? (
                <div
                  className="w-20 shrink-0 self-start overflow-hidden rounded border border-slate-200 bg-slate-100 dark:border-slate-700 dark:bg-slate-800"
                  style={cropStyle}
                  title={`${item.name} — kırpılmış önizleme`}
                />
              ) : (
                <div className="grid aspect-square w-20 shrink-0 self-start place-items-center rounded border border-dashed border-slate-300 text-center text-[9px] text-slate-400 dark:border-slate-700">
                  kutu yok
                </div>
              )}

              <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                <div className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    checked={r.keep}
                    disabled={busy || done}
                    onChange={(e) => setRow(item.item_id, { keep: e.target.checked })}
                    className="mt-1 size-4 shrink-0 accent-emerald-600"
                  />
                  <input
                    value={r.name}
                    disabled={busy || done || !r.keep}
                    onChange={(e) => setRow(item.item_id, { name: e.target.value })}
                    className="min-w-0 flex-1 rounded border border-slate-200 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-950"
                  />
                </div>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 pl-6 text-xs text-slate-500 dark:text-slate-400">
                  <span className="rounded bg-emerald-100 px-1.5 py-0.5 font-medium text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
                    {formatQuantity(item.quantity)}
                  </span>
                  <span>{categoryLabel(item.category)}</span>
                  {r.cropStatus !== "idle" && (
                    <span
                      className={
                        r.cropStatus === "done"
                          ? "text-emerald-600 dark:text-emerald-400"
                          : r.cropStatus === "error"
                            ? "text-rose-600 dark:text-rose-400"
                            : "text-slate-400"
                      }
                    >
                      {CROP_LABEL[r.cropStatus]}
                    </span>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      {error && <p className="text-xs text-rose-600 dark:text-rose-400">{error}</p>}

      {!done && ticket.items.length > 0 && (
        <button
          type="button"
          disabled={busy || keptCount === 0}
          onClick={() => void handleConfirm()}
          className="self-start rounded-md bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy
            ? "Onaylanıyor…"
            : `Onayla ve envantere ekle (${keptCount}/${ticket.items.length})`}
        </button>
      )}
      {done && (
        <p className="text-xs text-emerald-600 dark:text-emerald-400">
          Ürünler envantere eklendi; kırpılmış görselleri S3'te saklandı.
        </p>
      )}
    </div>
  );
}
