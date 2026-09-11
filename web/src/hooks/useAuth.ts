import { useCallback, useEffect, useRef, useState } from "react";
import {
  buildAuthorizeUrl,
  buildLogoutUrl,
  decodeJwtPayload,
  exchangeCodeForTokens,
  refreshTokens,
  type CognitoConfig,
  type TokenSet,
} from "../api/auth";
import { codeChallengeFromVerifier, generateCodeVerifier, generateState } from "../lib/pkce";

const TOKENS_KEY = "fridge.auth.tokens.v1";
const PKCE_KEY = "fridge.auth.pkce.v1";
const CALLBACK_PATH = "/auth/callback";

type AuthStatus = "loading" | "signed-out" | "signed-in" | "error";

interface PkceEntry {
  verifier: string;
  state: string;
}

function loadTokens(): TokenSet | null {
  try {
    const raw = sessionStorage.getItem(TOKENS_KEY);
    return raw ? (JSON.parse(raw) as TokenSet) : null;
  } catch {
    return null;
  }
}

function saveTokens(tokens: TokenSet | null) {
  try {
    if (tokens) sessionStorage.setItem(TOKENS_KEY, JSON.stringify(tokens));
    else sessionStorage.removeItem(TOKENS_KEY);
  } catch {
    // sessionStorage kapalıysa (gizli sekme kısıtlaması) sessizce yok say —
    // oturum sekme yenilenince zaten kaybolacaktı.
  }
}

/**
 * Cognito Hosted UI ile PKCE oturum yönetimi.
 *
 * `sessionStorage` kullanılır (localStorage değil): sekme kapanınca token
 * kaybolur — bu bir test aracı için doğru varsayılan, kalıcı oturum riski
 * taşımaz. `code_verifier`/`state` de aynı sebeple sessionStorage'da tutulur;
 * yalnızca redirect gidiş-dönüşü boyunca yaşar.
 */
export function useAuth(config: CognitoConfig | null) {
  const [tokens, setTokens] = useState<TokenSet | null>(loadTokens);
  const [status, setStatus] = useState<AuthStatus>(tokens ? "signed-in" : "signed-out");
  const [error, setError] = useState<string | null>(null);
  const refreshInFlight = useRef<Promise<TokenSet> | null>(null);

  // Callback yolunda ?code=&state= varsa değişimi tamamla.
  useEffect(() => {
    if (!config) return;
    if (window.location.pathname !== CALLBACK_PATH) return;

    const params = new URLSearchParams(window.location.search);
    const oauthError = params.get("error");
    if (oauthError) {
      setError(params.get("error_description") ?? oauthError);
      setStatus("error");
      window.history.replaceState({}, "", "/");
      return;
    }

    const code = params.get("code");
    const returnedState = params.get("state");
    if (!code || !returnedState) return;

    let cancelled = false;
    setStatus("loading");

    (async () => {
      let entry: PkceEntry | null = null;
      try {
        const raw = sessionStorage.getItem(PKCE_KEY);
        entry = raw ? (JSON.parse(raw) as PkceEntry) : null;
      } catch {
        entry = null;
      }
      if (!entry || entry.state !== returnedState) {
        if (!cancelled) {
          setError("Oturum durumu eşleşmedi (state) — güvenlik nedeniyle giriş iptal edildi.");
          setStatus("error");
        }
        window.history.replaceState({}, "", "/");
        return;
      }
      try {
        const tokenSet = await exchangeCodeForTokens(config, code, entry.verifier);
        if (cancelled) return;
        sessionStorage.removeItem(PKCE_KEY);
        saveTokens(tokenSet);
        setTokens(tokenSet);
        setStatus("signed-in");
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Giriş tamamlanamadı");
          setStatus("error");
        }
      } finally {
        window.history.replaceState({}, "", "/");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [config]);

  const login = useCallback(async () => {
    if (!config) return;
    const verifier = generateCodeVerifier();
    const state = generateState();
    const challenge = await codeChallengeFromVerifier(verifier);
    sessionStorage.setItem(PKCE_KEY, JSON.stringify({ verifier, state } satisfies PkceEntry));
    window.location.href = buildAuthorizeUrl(config, { codeChallenge: challenge, state });
  }, [config]);

  const logout = useCallback(() => {
    saveTokens(null);
    setTokens(null);
    setStatus("signed-out");
    if (config) window.location.href = buildLogoutUrl(config);
  }, [config]);

  /** Geçerli bir id_token döner; süresi dolmuşsa önce tazeler. Tazeleme
   * başarısız olursa oturumu kapatır ve `null` döner (çağıran yeniden girişe
   * yönlendirmeli). Eşzamanlı çağrılar tek bir tazeleme isteğini paylaşır.
   */
  const getValidIdToken = useCallback(async (): Promise<string | null> => {
    const current = tokens;
    if (!current || !config) return null;
    if (Date.now() < current.expiresAt) return current.idToken;
    if (!current.refreshToken) {
      logout();
      return null;
    }
    if (!refreshInFlight.current) {
      refreshInFlight.current = refreshTokens(config, current.refreshToken).finally(() => {
        refreshInFlight.current = null;
      });
    }
    try {
      const refreshed = await refreshInFlight.current;
      saveTokens(refreshed);
      setTokens(refreshed);
      return refreshed.idToken;
    } catch {
      logout();
      return null;
    }
  }, [tokens, config, logout]);

  const claims = tokens ? decodeJwtPayload(tokens.idToken) : null;
  const email = typeof claims?.email === "string" ? claims.email : null;

  return { status, error, isSignedIn: status === "signed-in", email, login, logout, getValidIdToken };
}
