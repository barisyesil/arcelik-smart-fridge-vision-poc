/**
 * İstemci tarafı küçültme.
 *
 * Bu tek adım üç şeyi birden iyileştirir: S3 depolamayı (~20×), Gemini token
 * maliyetini ve yükleme süresini. Atlanırsa sistem çalışır ama ücretsiz
 * katman daha hızlı dolar.
 */

const MAX_EDGE_PX = 1024;
const JPEG_QUALITY = 0.8;

export async function resizeToJpeg(file: File): Promise<{ blob: Blob; contentType: string }> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, MAX_EDGE_PX / Math.max(bitmap.width, bitmap.height));
  const width = Math.round(bitmap.width * scale);
  const height = Math.round(bitmap.height * scale);

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    throw new Error("Canvas 2D bağlamı alınamadı");
  }
  ctx.drawImage(bitmap, 0, 0, width, height);
  bitmap.close();

  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, "image/jpeg", JPEG_QUALITY),
  );
  if (!blob) {
    throw new Error("Görsel JPEG'e dönüştürülemedi");
  }

  return { blob, contentType: "image/jpeg" };
}
