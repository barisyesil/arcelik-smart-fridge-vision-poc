/**
 * Kontrol ekranı onayında bir ürünü, bounding box'a göre KIRPIP yüklenebilir
 * bir JPEG blob'una çevirir.
 *
 * Önemli: kaynak, kullanıcının cihazından yüklenen YEREL (küçültülmüş) blob'dur
 * — S3'ten gelen presigned URL DEĞİL. Yerel blob aynı-köken olduğu için canvas
 * "tainted" olmaz ve `toBlob` çalışır (piksel okunabilir). Kutular Gemini'nin
 * gördüğü (yani S3'e yüklenen) görsele göre 0-1000 normalize; aynı blob'dan
 * kırptığımız için koordinatlar birebir örtüşür. `cropImage.ts` yalnızca
 * GÖSTERİM (CSS) içindir; bu dosya yüklemek üzere gerçek piksel üretir.
 */

import type { BoundingBox } from "../api/types";
import { padBoxToAspect } from "./cropImage";

const COORD_MAX = 1000;
const CROP_QUALITY = 0.8;

/**
 * `shape`: mobilde ürün kartları 3:4/9:16 gösterildiği için kırpmayı o orana
 * genişletir (bkz. `padBoxToAspect`). `ratio=null` → modelin kutusu aynen. Oran
 * hesabı gerçek piksellerde yapılır; burada bitmap boyutları kullanılır.
 */
export async function cropToBlob(
  source: Blob,
  box: BoundingBox,
  shape: { ratio: number | null; marginFrac?: number } = { ratio: null },
): Promise<Blob> {
  const bitmap = await createImageBitmap(source);
  try {
    const shaped = padBoxToAspect(
      box,
      shape.ratio,
      bitmap.width,
      bitmap.height,
      shape.marginFrac ?? 0,
    );
    const left = Math.round((shaped.xmin / COORD_MAX) * bitmap.width);
    const top = Math.round((shaped.ymin / COORD_MAX) * bitmap.height);
    const width = Math.max(1, Math.round(((shaped.xmax - shaped.xmin) / COORD_MAX) * bitmap.width));
    const height = Math.max(
      1,
      Math.round(((shaped.ymax - shaped.ymin) / COORD_MAX) * bitmap.height),
    );

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      throw new Error("Canvas 2D bağlamı alınamadı");
    }
    ctx.drawImage(bitmap, left, top, width, height, 0, 0, width, height);

    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", CROP_QUALITY),
    );
    if (!blob) {
      throw new Error("Crop JPEG'e dönüştürülemedi");
    }
    return blob;
  } finally {
    bitmap.close();
  }
}
