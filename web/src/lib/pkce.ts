/**
 * PKCE (RFC 7636) yardımcıları — Authorization Code + PKCE akışı için.
 *
 * Mobil uygulama secret taşımadığı gibi (SRS NFR-SEC-001), bu web test aracı
 * da taşımaz: Cognito public client + PKCE kullanılır. `code_verifier`
 * tarayıcıda üretilip `sessionStorage`'da saklanır (sekme kapanınca silinir);
 * sunucuya yalnızca SHA-256'sı (`code_challenge`) gider.
 *
 * S256 hesaplaması RFC 7636 Ek B test vektörüyle doğrulanmıştır:
 * verifier "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk" ->
 * challenge "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM".
 */

function base64UrlEncode(bytes: Uint8Array): string {
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function generateCodeVerifier(): string {
  // RFC 7636: 43-128 karakter, [A-Za-z0-9-._~]. 32 rastgele byte'ın
  // base64url'i 43 karakter üretir — minimum uzunluğu tam karşılar.
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return base64UrlEncode(bytes);
}

export async function codeChallengeFromVerifier(verifier: string): Promise<string> {
  const data = new TextEncoder().encode(verifier);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return base64UrlEncode(new Uint8Array(digest));
}

export function generateState(): string {
  // CSRF koruması: authorize isteğiyle giden değer, callback'te aynen dönmeli.
  return base64UrlEncode(crypto.getRandomValues(new Uint8Array(16)));
}
