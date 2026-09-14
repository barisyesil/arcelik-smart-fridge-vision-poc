import { useCallback, useEffect, useMemo, useState } from "react";
import type { CognitoConfig } from "./api/auth";
import { postAssessment, type ApiConfig } from "./api/client";
import type { DiscardReason, FreshnessAssessmentRequest, InventoryItemDto } from "./api/types";
import { AccountBar } from "./components/AccountBar";
import { AssessmentModal } from "./components/AssessmentModal";
import { AuthGate } from "./components/AuthGate";
import { Disclaimer } from "./components/Disclaimer";
import { DraftReviewPanel } from "./components/DraftReviewPanel";
import { PromptLab } from "./components/PromptLab";
import { InventoryList } from "./components/InventoryList";
import { ProfileSetup } from "./components/ProfileSetup";
import { RecipesPanel } from "./components/RecipesPanel";
import { ReviewQueuePanel } from "./components/ReviewQueuePanel";
import { SettingsBar } from "./components/SettingsBar";
import { ShoppingPanel } from "./components/ShoppingPanel";
import { UndoToast } from "./components/UndoToast";
import { UploadPanel } from "./components/UploadPanel";
import { useAuth } from "./hooks/useAuth";
import { useCandidates } from "./hooks/useCandidates";
import { useInventory } from "./hooks/useInventory";
import { useProfile } from "./hooks/useProfile";
import { useRecipes } from "./hooks/useRecipes";
import { useReviewQueue } from "./hooks/useReviewQueue";
import { useSettings } from "./hooks/useSettings";
import { useShopping } from "./hooks/useShopping";
import { useSwipeActions } from "./hooks/useSwipeActions";
import { useUpload } from "./hooks/useUpload";

type Tab = "envanter" | "kontrol" | "liste" | "tarifler";

/** URL hash'i `#lab` içeriyorsa Prompt Lab moduna geç. */
function useLabMode(): boolean {
  const [labMode, setLabMode] = useState(() => window.location.hash.includes("lab"));
  useEffect(() => {
    const onHash = () => setLabMode(window.location.hash.includes("lab"));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  return labMode;
}

export default function App() {
  const settings = useSettings();
  const labMode = useLabMode();

  // Cognito PKCE akışı bu deploy'a özel domain/client'a ihtiyaç duyar; ikisi
  // de girilmeden auth denenmez (useAuth `config: null` ile no-op çalışır).
  const cognitoConfig = useMemo<CognitoConfig | null>(() => {
    if (!settings.config.cognitoDomain || !settings.config.cognitoClientId) return null;
    const origin = window.location.origin;
    return {
      domain: settings.config.cognitoDomain.replace(/\/$/, ""),
      clientId: settings.config.cognitoClientId,
      redirectUri: `${origin}/auth/callback`,
      logoutUri: `${origin}/`,
    };
  }, [settings.config.cognitoDomain, settings.config.cognitoClientId]);

  const auth = useAuth(cognitoConfig);

  const apiConfig = useMemo<ApiConfig>(
    () => ({ baseUrl: settings.config.baseUrl, getIdToken: auth.getValidIdToken }),
    [settings.config.baseUrl, auth.getValidIdToken],
  );

  const profile = useProfile(apiConfig, auth.isSignedIn && settings.isConfigured);
  const dataEnabled = auth.isSignedIn && Boolean(profile.profile);

  const inventory = useInventory(apiConfig, dataEnabled);
  const reviewQueue = useReviewQueue(apiConfig, dataEnabled);
  const shopping = useShopping(apiConfig, dataEnabled);
  const candidates = useCandidates(apiConfig, dataEnabled);
  const recipes = useRecipes(apiConfig, dataEnabled);
  const swipeActions = useSwipeActions(apiConfig);
  const { tickets, startUpload, setConfirmState } = useUpload(apiConfig);

  const [tab, setTab] = useState<Tab>("envanter");
  const [assessingItem, setAssessingItem] = useState<InventoryItemDto | null>(null);

  const completedWithItems = tickets.filter(
    (ticket) => ticket.status === "COMPLETED" && ticket.items.length > 0,
  );

  const handleFileSelected = useCallback(
    (file: File) => {
      void startUpload(file, () => {
        void inventory.refresh();
      });
    },
    [startUpload, inventory],
  );

  // Kontrol kuyruğu ve öneriler swipe sonucundan doğrudan etkilenir; üçünü
  // birlikte tazelemek arayüzün her sekmede tutarlı kalmasını sağlar.
  const refreshAfterSwipe = useCallback(
    () => Promise.all([inventory.refresh(), reviewQueue.refresh(), candidates.refresh()]),
    [inventory, reviewQueue, candidates],
  );

  const handleSwipe = useCallback(
    async (item: InventoryItemDto, type: "CONSUMED" | "DISCARDED", reason?: DiscardReason) => {
      await swipeActions.swipe(item.item_id, item.name, type, reason);
      await refreshAfterSwipe();
    },
    [swipeActions, refreshAfterSwipe],
  );

  const handleUndo = useCallback(async () => {
    await swipeActions.undo();
    await refreshAfterSwipe();
  }, [swipeActions, refreshAfterSwipe]);

  const handleAssessmentSubmit = useCallback(
    async (payload: FreshnessAssessmentRequest) => {
      if (!assessingItem) return;
      await postAssessment(apiConfig, assessingItem.item_id, payload);
      await Promise.all([inventory.refresh(), reviewQueue.refresh()]);
    },
    [apiConfig, assessingItem, inventory, reviewQueue],
  );

  const handleAcceptCandidate = useCallback(
    async (candidateId: string) => {
      await candidates.accept(candidateId);
      await shopping.refresh();
    },
    [candidates, shopping],
  );

  // Prompt Lab yerel dev aracıdır: cloud API/Cognito gerektirmez. Tüm hook'lar
  // yukarıda çağrıldıktan SONRA (React hook kuralları) auth gate'lerinden önce
  // devreye girer — böylece giriş yapmadan da erişilebilir.
  if (labMode) {
    return <PromptLab onExit={() => (window.location.hash = "")} />;
  }

  // --- Aşamalı gate'ler: bağlantı ayarları -> Cognito girişi -> profil kaydı ---

  if (!settings.isConfigured) {
    return (
      <div className="mx-auto flex min-h-screen max-w-2xl flex-col gap-6 px-4 py-8 sm:px-6">
        <header className="flex items-start justify-between gap-2">
          <div className="flex flex-col gap-1">
            <h1 className="text-xl font-semibold text-slate-900 dark:text-white">
              Akıllı Buzdolabı — Test Arayüzü
            </h1>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Faz 2 · mobil cloud entegrasyonu test aracı
            </p>
          </div>
          <a
            href="#lab"
            className="shrink-0 rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            🧪 Prompt Lab
          </a>
        </header>
        <SettingsBar config={settings.config} onChange={settings.setConfig} />
        <div className="rounded-xl border border-dashed border-slate-300 px-6 py-10 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
          Devam etmeden önce yukarıdan API adresini ve Cognito bilgilerini girin
          (`cdk deploy` çıktıları — bkz. infra/README.md).
        </div>
      </div>
    );
  }

  if (!auth.isSignedIn) {
    return <AuthGate status={auth.status} error={auth.error} onLogin={() => void auth.login()} />;
  }

  if (profile.needsRegistration) {
    return (
      <ProfileSetup
        onRegister={profile.register}
        isRegistering={profile.isRegistering}
        registerError={profile.registerError}
      />
    );
  }

  if (!profile.profile) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-slate-400">
        {profile.error ?? "Profil yükleniyor…"}
      </div>
    );
  }

  const TABS: { id: Tab; label: string; badge?: number }[] = [
    { id: "envanter", label: "Ürünlerim" },
    { id: "kontrol", label: "Kontrol", badge: reviewQueue.totalPending },
    { id: "liste", label: "Listem", badge: candidates.candidates.length },
    { id: "tarifler", label: "Tarifler" },
  ];

  return (
    <div className="mx-auto flex min-h-screen max-w-5xl flex-col gap-6 px-4 py-8 sm:px-6">
      <header className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-semibold text-slate-900 dark:text-white">
            Akıllı Buzdolabı — Test Arayüzü
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Faz 2 · fotoğraf yükle, kontrol kuyruğunu değerlendir, alışverişi ve
            tarifleri gözden geçir
          </p>
        </div>
        <a
          href="#lab"
          className="shrink-0 rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          🧪 Prompt Lab
        </a>
      </header>

      <AccountBar
        email={auth.email}
        profile={profile.profile}
        onLogout={auth.logout}
        onNotificationModeChange={profile.updateNotificationMode}
      />
      <SettingsBar config={settings.config} onChange={settings.setConfig} />
      <Disclaimer />

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-slate-700 dark:text-slate-200">Fotoğraf yükle</h2>
        <UploadPanel tickets={tickets} onFileSelected={handleFileSelected} disabled={false} />
      </section>

      {completedWithItems.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-medium text-slate-700 dark:text-slate-200">
            Kontrol ekranı — onayla ve envantere ekle
          </h2>
          <div className="flex flex-col gap-3">
            {completedWithItems.map((ticket) => (
              <DraftReviewPanel
                key={ticket.uploadId}
                ticket={ticket}
                apiConfig={apiConfig}
                onConfirmed={() => void inventory.refresh()}
                onStateChange={(s) => setConfirmState(ticket.uploadId, s)}
              />
            ))}
          </div>
        </section>
      )}

      <nav className="flex gap-1 border-b border-slate-200 dark:border-slate-800">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`relative px-3 py-2 text-sm font-medium ${
              tab === t.id
                ? "border-b-2 border-slate-900 text-slate-900 dark:border-white dark:text-white"
                : "text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
            }`}
          >
            {t.label}
            {!!t.badge && (
              <span className="ml-1.5 rounded-full bg-slate-200 px-1.5 py-0.5 text-[10px] font-semibold text-slate-600 dark:bg-slate-700 dark:text-slate-300">
                {t.badge}
              </span>
            )}
          </button>
        ))}
      </nav>

      {tab === "envanter" && (
        <section className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-slate-700 dark:text-slate-200">Envanter</h2>
            <button
              type="button"
              onClick={() => void inventory.refresh()}
              className="text-xs text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
            >
              Yenile
            </button>
          </div>
          <InventoryList
            items={inventory.items}
            isLoading={inventory.isLoading}
            error={inventory.error}
            onUpdate={inventory.update}
            onDelete={inventory.remove}
            onSwipe={handleSwipe}
            onOpenAssessment={setAssessingItem}
          />
        </section>
      )}

      {tab === "kontrol" && (
        <section className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-slate-700 dark:text-slate-200">
              Bugünkü Kontrol
            </h2>
            <button
              type="button"
              onClick={() => void reviewQueue.refresh()}
              className="text-xs text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
            >
              Yenile
            </button>
          </div>
          <ReviewQueuePanel
            entries={reviewQueue.queue}
            totalPending={reviewQueue.totalPending}
            isLoading={reviewQueue.isLoading}
            error={reviewQueue.error}
            onUpdate={inventory.update}
            onDelete={inventory.remove}
            onSwipe={handleSwipe}
            onOpenAssessment={setAssessingItem}
          />
        </section>
      )}

      {tab === "liste" && (
        <section className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-slate-700 dark:text-slate-200">
              Alışveriş Listem
            </h2>
            <button
              type="button"
              onClick={() => void Promise.all([shopping.refresh(), candidates.refresh()])}
              className="text-xs text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
            >
              Yenile
            </button>
          </div>
          <ShoppingPanel
            candidates={candidates.candidates}
            active={shopping.active}
            completed={shopping.completed}
            isLoading={shopping.isLoading}
            error={shopping.error}
            onAcceptCandidate={handleAcceptCandidate}
            onDismissCandidate={candidates.dismiss}
            onAddItem={(name) => shopping.add({ name })}
            onComplete={(id) => shopping.update(id, { state: "COMPLETED" })}
            onRemove={shopping.remove}
          />
        </section>
      )}

      {tab === "tarifler" && (
        <section className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-slate-700 dark:text-slate-200">Tarifler</h2>
            <button
              type="button"
              onClick={() => void recipes.refresh()}
              className="text-xs text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
            >
              Yenile
            </button>
          </div>
          <RecipesPanel
            recommendations={recipes.recommendations}
            datasetVersion={recipes.datasetVersion}
            isLoading={recipes.isLoading}
            error={recipes.error}
          />
        </section>
      )}

      {assessingItem && (
        <AssessmentModal
          item={assessingItem}
          onSubmit={handleAssessmentSubmit}
          onClose={() => setAssessingItem(null)}
        />
      )}

      {swipeActions.pendingUndo && (
        <UndoToast pending={swipeActions.pendingUndo} onUndo={() => void handleUndo()} />
      )}
    </div>
  );
}
