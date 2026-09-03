/**
 * Tazelik tarihi türetilmiş bir tahmindir, üreticinin bastığı SKT/TETT
 * değildir. Bu uyarı her ekranda görünür olmalı; kaldırılamaz.
 */
export function Disclaimer() {
  return (
    <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-900 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-200">
      Buradaki tarihler ürün kategorisine göre hesaplanmış <strong>tahminlerdir</strong>.
      Ambalaj üzerindeki tarih esastır.
    </p>
  );
}
