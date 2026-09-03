export type UrgencyLevel = "expired" | "soon" | "ok";

/** Backend `estimated_freshness_date` alanını YYYY-MM-DD döndürür (UTC gün, saatsiz). */
export function daysUntil(isoDate: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(`${isoDate}T00:00:00`);
  const diffMs = target.getTime() - today.getTime();
  return Math.round(diffMs / 86_400_000);
}

/** 0-2 gün: kırmızı, 3-5 gün: sarı, ötesi: yeşil. Sabit ama F-06'nın Faz 1
 * kapsamındaki tek gösterge şekli — arayüz içi basit rozet. */
export function urgencyOf(daysLeft: number): UrgencyLevel {
  if (daysLeft < 0) return "expired";
  if (daysLeft <= 2) return "soon";
  return "ok";
}

export function formatDaysLeft(daysLeft: number): string {
  if (daysLeft < 0) return `${Math.abs(daysLeft)} gün önce geçti`;
  if (daysLeft === 0) return "Bugün";
  if (daysLeft === 1) return "Yarın";
  return `${daysLeft} gün kaldı`;
}
