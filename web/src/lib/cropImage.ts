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
 * Mobil kart formatları için hedef en-boy oranı seçenekleri (genişlik/yükseklik,
 * PİKSEL bazında). Gemini'nin döndürdüğü kutu ürüne "tam otursa" bile mobilde
 * 3:4 / 9:16 kartlarda gösterildiği için, kırpmayı bu orana genişleterek
 * kartın kenarlarında tuhaf boşluk/kırpılma oluşmasını engelleriz. "tight" =
 * modelin verdiği kutuyu olduğu gibi kullan (genişletme yok).
 */
export const CROP_ASPECT_OPTIONS: { key: string; label: string; ratio: number | null }[] = [
  { key: "tight", label: "Kutuya tam (tight)", ratio: null },
  { key: "3:4", label: "3:4 (mobil kart)", ratio: 3 / 4 },
  { key: "9:16", label: "9:16 (dikey)", ratio: 9 / 16 },
  { key: "1:1", label: "1:1 (kare)", ratio: 1 },
];

/**
 * Bir bounding box'ı (0-1000) hedef PİKSEL en-boy oranına genişletir + isteğe
 * bağlı kenar payı ekler. Kutu YALNIZCA büyütülür (içerik kırpılmaz): dar olan
 * kenar, hedef orana ulaşana dek merkez etrafında açılır. Görsel sınırlarını
 * aşarsa önce pencere içeri kaydırılır, sığmıyorsa boyut sınıra çekilir.
 *
 * box_2d her iki eksende 0-1000'e AYRI normalize olduğu için oran hesabı piksel
 * uzayında yapılmalı — bu yüzden görselin gerçek en/boy'u gerekir. `ratio=null`
 * ise kutu değiştirilmeden döner.
 */
export function padBoxToAspect(
  box: BoundingBox,
  ratio: number | null,
  imageWidth: number,
  imageHeight: number,
  marginFrac = 0,
): BoundingBox {
  if (!ratio || imageWidth <= 0 || imageHeight <= 0) return box;

  const pxX = imageWidth / COORD_MAX;
  const pxY = imageHeight / COORD_MAX;
  let leftPx = box.xmin * pxX;
  let topPx = box.ymin * pxY;
  let wPx = (box.xmax - box.xmin) * pxX;
  let hPx = (box.ymax - box.ymin) * pxY;

  // 1) Kenar payı — merkez etrafında büyüt.
  const addW = wPx * marginFrac;
  const addH = hPx * marginFrac;
  leftPx -= addW / 2;
  topPx -= addH / 2;
  wPx += addW;
  hPx += addH;

  // 2) Hedef orana ulaşana dek DAR kenarı aç (asla küçültme).
  const cx = leftPx + wPx / 2;
  const cy = topPx + hPx / 2;
  if (wPx / hPx < ratio) {
    wPx = hPx * ratio;
  } else {
    hPx = wPx / ratio;
  }

  // 3) Görselden büyükse boyutu sınıra çek (oranı koru).
  if (wPx > imageWidth) {
    wPx = imageWidth;
    hPx = wPx / ratio;
  }
  if (hPx > imageHeight) {
    hPx = imageHeight;
    wPx = hPx * ratio;
  }

  // 4) Pencereyi merkezle, sonra sınır içine kaydır.
  leftPx = cx - wPx / 2;
  topPx = cy - hPx / 2;
  leftPx = Math.max(0, Math.min(leftPx, imageWidth - wPx));
  topPx = Math.max(0, Math.min(topPx, imageHeight - hPx));

  const clamp = (v: number) => Math.max(0, Math.min(COORD_MAX, Math.round(v)));
  return {
    xmin: clamp((leftPx / imageWidth) * COORD_MAX),
    ymin: clamp((topPx / imageHeight) * COORD_MAX),
    xmax: clamp(((leftPx + wPx) / imageWidth) * COORD_MAX),
    ymax: clamp(((topPx + hPx) / imageHeight) * COORD_MAX),
  };
}

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
