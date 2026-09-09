/**
 * Bounding box'a göre istemci tarafı kırpma (Faz 1 prototipi).
 *
 * Gemini'nin döndürdüğü kutuları kaynak fotoğrafa uygulayıp her ürünü ayrı
 * gösterir. Kırpma SALT CSS ile yapılır (`background-image` + `background-size`
 * + `background-position`) — canvas KULLANILMAZ.
 *
 * Neden canvas değil: canvas'tan piksel okumak (toBlob/toDataURL) kaynağın CORS
 * başlığı (`Access-Control-Allow-Origin`) döndürmesini zorunlu kılar; S3
 * presigned GET yanıtı bunu her zaman döndürmez ve görsel "tainted" olur.
 * CSS arka plan kırpması ise sıradan bir `<img src>` gibi davranır: yalnızca
 * gösterim yapar, piksel okumaz, dolayısıyla CORS gerektirmez ve S3 CORS
 * yapılandırmasından bağımsız çalışır.
 *
 * Sonraki fazda kırpma buluta (Lambda + Pillow + S3 `crops/`) taşınınca bu
 * dosya kaldırılıp yerine hazır crop URL'leri kullanılacak.
 */

import type { CSSProperties } from "react";
import type { BoundingBox } from "../api/types";

const COORD_MAX = 1000;

/**
 * Kaynak görselin doğal boyutunu okur. `crossOrigin` verilmez: yalnızca
 * `naturalWidth/Height` okunur (piksel değil), bu CORS gerektirmez. Boyut,
 * kırpılan kutunun en-boy oranını doğru kurmak için gerekir.
 */
export function loadImageSize(url: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight });
    img.onerror = () => reject(new Error("Kaynak görsel yüklenemedi"));
    img.src = url;
  });
}

/**
 * Bir kutuyu, kaynak görseli arka plan olarak kullanıp yalnızca o bölgeyi
 * gösterecek CSS stiline çevirir. Kapsayıcı div'e uygulanır.
 *
 * Yüzde tabanlı `background-position` "sprite kırpma" formülü:
 *   posX% = xminFrac / (1 - bwFrac) * 100
 * `background-size` ise görseli, kutu bölgesi kapsayıcıyı dolduracak biçimde
 * ölçekler. `aspectRatio` kutunun gerçek piksel oranına ayarlanır ki görsel
 * bozulmadan gösterilsin.
 */
export function buildCropStyle(
  sourceUrl: string,
  box: BoundingBox,
  imageWidth: number,
  imageHeight: number,
): CSSProperties {
  const bwFrac = (box.xmax - box.xmin) / COORD_MAX;
  const bhFrac = (box.ymax - box.ymin) / COORD_MAX;
  const xminFrac = box.xmin / COORD_MAX;
  const yminFrac = box.ymin / COORD_MAX;

  const posX = bwFrac < 1 ? (xminFrac / (1 - bwFrac)) * 100 : 0;
  const posY = bhFrac < 1 ? (yminFrac / (1 - bhFrac)) * 100 : 0;

  return {
    backgroundImage: `url("${sourceUrl}")`,
    backgroundRepeat: "no-repeat",
    backgroundSize: `${100 / bwFrac}% ${100 / bhFrac}%`,
    backgroundPosition: `${posX}% ${posY}%`,
    aspectRatio: `${bwFrac * imageWidth} / ${bhFrac * imageHeight}`,
  };
}
