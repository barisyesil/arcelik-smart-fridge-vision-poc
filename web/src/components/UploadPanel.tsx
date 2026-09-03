import { useRef, useState, type DragEvent } from "react";
import type { UploadTicket } from "../hooks/useUpload";
import { uploadStatusLabel } from "../lib/labels";

interface UploadPanelProps {
  tickets: UploadTicket[];
  onFileSelected: (file: File) => void;
  disabled: boolean;
}

const STATUS_DOT: Record<string, string> = {
  UPLOADING: "bg-slate-400 animate-pulse",
  PENDING: "bg-slate-400 animate-pulse",
  PROCESSING: "bg-blue-500 animate-pulse",
  COMPLETED: "bg-emerald-500",
  FAILED: "bg-rose-500",
  TIMED_OUT: "bg-amber-500",
};

export function UploadPanel({ tickets, onFileSelected, disabled }: UploadPanelProps) {
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
    const file = event.dataTransfer.files[0];
    if (file) onFileSelected(file);
  };

  return (
    <div className="flex flex-col gap-3">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        onClick={() => !disabled && inputRef.current?.click()}
        className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
          isDragging
            ? "border-emerald-400 bg-emerald-50 dark:bg-emerald-950/20"
            : "border-slate-300 hover:border-slate-400 dark:border-slate-700"
        } ${disabled ? "pointer-events-none opacity-50" : ""}`}
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.5}
          className="size-8 text-slate-400"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 7.5m0 0L7.5 12m4.5-4.5v13.5"
          />
        </svg>
        <p className="text-sm text-slate-600 dark:text-slate-300">
          Gıda fotoğrafını sürükleyin veya <span className="font-medium text-slate-900 dark:text-white">seçmek için tıklayın</span>
        </p>
        <p className="text-xs text-slate-400">JPEG/PNG · otomatik olarak küçültülür</p>
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) onFileSelected(file);
            e.target.value = "";
          }}
        />
      </div>

      {tickets.length > 0 && (
        <ul className="flex flex-col gap-1.5">
          {tickets.map((ticket) => (
            <li
              key={ticket.uploadId}
              className="flex items-center gap-2.5 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-800 dark:bg-slate-900"
            >
              <span
                className={`size-2 shrink-0 rounded-full ${STATUS_DOT[ticket.status] ?? "bg-slate-300"}`}
              />
              <span className="flex-1 truncate text-slate-700 dark:text-slate-200">
                {ticket.fileName}
              </span>
              <span className="text-xs text-slate-500">
                {ticket.status === "COMPLETED"
                  ? `${ticket.itemCount} ürün bulundu`
                  : ticket.status === "TIMED_OUT"
                    ? "60 sn içinde yanıt gelmedi"
                    : ticket.error ?? uploadStatusLabel(ticket.status)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
