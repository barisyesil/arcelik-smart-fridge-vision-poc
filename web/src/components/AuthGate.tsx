interface AuthGateProps {
  status: "loading" | "signed-out" | "signed-in" | "error";
  error: string | null;
  onLogin: () => void;
}

/**
 * Cognito Hosted UI oturum durumuna göre giriş ekranı veya boşluk gösterir.
 * `signed-in` durumunda hiçbir şey render etmez — `App` asıl içeriği gösterir.
 */
export function AuthGate({ status, error, onLogin }: AuthGateProps) {
  if (status === "signed-in") return null;

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-4 px-4 text-center">
      <h1 className="text-lg font-semibold text-slate-900 dark:text-white">
        Akıllı Buzdolabı — Test Arayüzü
      </h1>
      <p className="text-sm text-slate-500 dark:text-slate-400">
        Devam etmek için Cognito hesabınızla giriş yapın. Kimlik doğrulama
        Amazon Cognito Hosted UI üzerinden gerçekleşir; şifreniz bu uygulamadan
        geçmez.
      </p>

      {status === "loading" && (
        <p className="text-sm text-slate-400">Giriş tamamlanıyor…</p>
      )}

      {status === "error" && error && (
        <p className="w-full rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/40 dark:bg-rose-950/20 dark:text-rose-300">
          {error}
        </p>
      )}

      {status !== "loading" && (
        <button
          type="button"
          onClick={onLogin}
          className="rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-medium text-white hover:bg-slate-800 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-100"
        >
          Cognito ile Giriş Yap / Kaydol
        </button>
      )}
    </div>
  );
}
