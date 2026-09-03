import { useCallback, useRef, useState } from "react";
import { createUpload, getUploadStatus, uploadToS3, type ApiConfig } from "../api/client";
import type { UploadStatusValue } from "../api/types";
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
      const { blob, contentType } = await resizeToJpeg(file);
      const presign = await createUpload(config);

      setTickets((prev) => [
        {
          uploadId: presign.upload_id,
          fileName: file.name,
          status: "UPLOADING",
          error: null,
          itemCount: 0,
        },
        ...prev,
      ]);

      await uploadToS3(presign, blob, contentType);
      patchTicket(presign.upload_id, { status: "PENDING" });
      pollStatus(presign.upload_id, onSettled);
    },
    [config, patchTicket, pollStatus],
  );

  return { tickets, startUpload };
}
