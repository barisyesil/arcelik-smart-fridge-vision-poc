/**
 * Cognito Hosted UI ile Authorization Code + PKCE akışı.
 *
 * Bu dosya yalnızca Cognito'nun `/oauth2/*` uçlarıyla konuşur; token'ların
 * saklanması ve tazelenmesi `hooks/useAuth.ts`'nin işidir. Mobil uygulama ile
 * aynı akışı (public client + PKCE) kullanır — burada da client secret yok.
 */

export interface CognitoConfig {
  domain: string; // örn. https://fridge-123456789012.auth.eu-central-1.amazoncognito.com
  clientId: string;
  redirectUri: string; // örn. http://localhost:5173/auth/callback
  logoutUri: string; // örn. http://localhost:5173/
}

export interface TokenResponse {
  id_token: string;
  access_token: string;
  refresh_token?: string;
  expires_in: number;
  token_type: string;
}

export interface TokenSet {
  idToken: string;
  accessToken: string;
  refreshToken: string | null;
  /** Epoch ms — `expires_in` saniyesinden türetilir. */
  expiresAt: number;
}

export class AuthError extends Error {}

export function buildAuthorizeUrl(
  config: CognitoConfig,
  params: { codeChallenge: string; state: string },
): string {
  const url = new URL(`${config.domain}/oauth2/authorize`);
  url.searchParams.set("client_id", config.clientId);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("scope", "openid email profile");
  url.searchParams.set("redirect_uri", config.redirectUri);
  url.searchParams.set("code_challenge", params.codeChallenge);
  url.searchParams.set("code_challenge_method", "S256");
  url.searchParams.set("state", params.state);
  return url.toString();
}

export function buildLogoutUrl(config: CognitoConfig): string {
  const url = new URL(`${config.domain}/logout`);
  url.searchParams.set("client_id", config.clientId);
  url.searchParams.set("logout_uri", config.logoutUri);
  return url.toString();
}

function toTokenSet(raw: TokenResponse): TokenSet {
  return {
    idToken: raw.id_token,
    accessToken: raw.access_token,
    refreshToken: raw.refresh_token ?? null,
    // 60 saniyelik pay: ağ gecikmesi ve saat sapması yüzünden "tam sınırda"
    // bir token'ı geçerli sanıp isteği başlatmayı önler.
    expiresAt: Date.now() + (raw.expires_in - 60) * 1000,
  };
}

async function postForm(url: string, body: Record<string, string>): Promise<TokenResponse> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(body),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new AuthError(`Cognito token isteği başarısız (${response.status}): ${text}`);
  }
  return (await response.json()) as TokenResponse;
}

export async function exchangeCodeForTokens(
  config: CognitoConfig,
  code: string,
  codeVerifier: string,
): Promise<TokenSet> {
  const raw = await postForm(`${config.domain}/oauth2/token`, {
    grant_type: "authorization_code",
    client_id: config.clientId,
    code,
    redirect_uri: config.redirectUri,
    code_verifier: codeVerifier,
  });
  return toTokenSet(raw);
}

export async function refreshTokens(config: CognitoConfig, refreshToken: string): Promise<TokenSet> {
  const raw = await postForm(`${config.domain}/oauth2/token`, {
    grant_type: "refresh_token",
    client_id: config.clientId,
    refresh_token: refreshToken,
  });
  // Cognito refresh yanıtında yeni refresh_token döndürmez; eskisini koru.
  return { ...toTokenSet(raw), refreshToken };
}

/** JWT gövdesini imza doğrulaması OLMADAN çözer — yalnız görüntüleme/süre
 * kontrolü için. Gerçek doğrulama her zaman API Gateway JWT authorizer'da olur.
 */
export function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const [, payload] = token.split(".");
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}
