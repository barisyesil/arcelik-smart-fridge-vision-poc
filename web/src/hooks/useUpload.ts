import { useCallback, useRef, useState } from "react";
import { createUpload, getUploadStatus, uploadToS3, type ApiConfig } from "../api/client";
import type { InventoryItemDto, UploadStatusValue } from "../api/types";
import { resizeToJpeg } from "../lib/resizeImage";

const POLL_INTERVAL_MS = 2000;
// Tarayıcı bu süre sonunda sorgulamayı bırakır ve kullanıcıya "envanterinizi
// kontrol edin" mesajı gösterir. İş kaybolmaz, sadece bildirim gecikir;
// extractor arka planda çalışmaya devam eder.
const POLL_TIMEOUT_MS = 60_000;

export interface UploadTicket {
  uploadId: string;
  fileName: string;
  status: UploadStatusValue | "UPLOADING" | "TIMED_OUT";
  error: string | null;
  itemCount: number;
  //: İşlem tamamlandığında dolan sonuç: bulunan (DRAFT) ürünler ve kaynak
  //: fotoğrafın presigned URL'si. Tamamlanana kadar boş kalırlar.
  items: InventoryItemDto[];
  sourceImageUrl: string | null;
  //: S3'e yüklenen KÜÇÜLTÜLMÜŞ blob ve ondan üretilen yerel (aynı-köken) object
  //: URL. Kontrol ekranı kırpma önizlemesi ve onayda crop üretimi bunları
  //: kullanır — böylece S3 CORS'a takılmadan piksel okunur.
  sourceBlob: Blob | null;
  sourceObjectUrl: string | null;
  //: Backend aşama süreleri (ms) + istemci zaman damgaları — darboğaz analizi.
  timings: Record<string, number> | null;
  startedAt: number;
  uploadedAt: number | null;
  completedAt: number | null;
  //: Kontrol ekranı yaşam döngüsü: onay bekliyor / onaylanıyor / onaylandı.
  confirmState: "PENDING_REVIEW" | "CONFIRMING" | "CONFIRMED";
}

export function useUpload(config: ApiConfig) {
  const [tickets, setTickets] = useState<UploadTicket[]>([]);
  const timers = useRef(new Map<string, ReturnType<typeof setInterval>>());

  const patchTicket = useCallback((uploadId: string, patch: Partial<UploadTicket>) => {
    setTickets((prev) =>
      prev.map((ticket) => (ticket.uploadId === uploadId ? { ...ticket, ...patch } : ticket)),
    );
  }, []);

  const pollStatus = useCallback(
    (uploadId: string, onSettled: () => void) => {
      const startedAt = Date.now();
      const interval = setInterval(async () => {
        if (Date.now() - startedAt > POLL_TIMEOUT_MS) {
          clearInterval(interval);
          timers.current.delete(uploadId);
          patchTicket(uploadId, { status: "TIMED_OUT" });
          onSettled();
          return;
        }
        try {
          const result = await getUploadStatus(config, uploadId);
          if (result.status === "COMPLETED" || result.status === "FAILED") {
            clearInterval(interval);
            timers.current.delete(uploadId);
            patchTicket(uploadId, {
              status: result.status,
              error: result.error,
              itemCount: result.items.length,
              items: result.items,
              sourceImageUrl: result.source_image_url,
              timings: result.timings ?? null,
              completedAt: Date.now(),
            });
            onSettled();
          }
        } catch (err) {
          clearInterval(interval);
          timers.current.delete(uploadId);
          patchTicket(uploadId, {
            status: "FAILED",
            error: err instanceof Error ? err.message : "Durum sorgulanamadı",
          });
          onSettled();
        }
      }, POLL_INTERVAL_MS);
      timers.current.set(uploadId, interval);
    },
    [config, patchTicket],
  );

  const startUpload = useCallback(
    async (file: File, onSettled: () => void) => {
      const startedAt = Date.now();
      const { blob, contentType } = await resizeToJpeg(file);
      const presign = await createUpload(config);
      const objectUrl = URL.createObjectURL(blob);

      setTickets((prev) => [
        {
          uploadId: presign.upload_id,
          fileName: file.name,
          status: "UPLOADING",
          error: null,
          itemCount: 0,
          items: [],
          sourceImageUrl: null,
          sourceBlob: blob,
          sourceObjectUrl: objectUrl,
          timings: null,
          startedAt,
          uploadedAt: null,
          completedAt: null,
          confirmState: "PENDING_REVIEW",
        },
        ...prev,
      ]);

      await uploadToS3(presign, blob, contentType);
      patchTicket(presign.upload_id, { status: "PENDING", uploadedAt: Date.now() });
      pollStatus(presign.upload_id, onSettled);
    },
    [config, patchTicket, pollStatus],
  );

  const setConfirmState = useCallback(
    (uploadId: string, confirmState: UploadTicket["confirmState"]) =>
      patchTicket(uploadId, { confirmState }),
    [patchTicket],
  );

  return { tickets, startUpload, setConfirmState };
}
