import { useCallback, useEffect, useState } from "react";
import { getMe, putNotificationPreferences, registerProfile, type ApiConfig } from "../api/client";
import { ApiRequestError } from "../api/client";
import type { NotificationMode, UserProfileDto } from "../api/types";

interface UseProfileResult {
  profile: UserProfileDto | null;
  isLoading: boolean;
  /** Profil hiç oluşturulmamış (backend 404 döndü) — kayıt formu gösterilmeli. */
  needsRegistration: boolean;
  error: string | null;
  register: (displayName: string, fridgeId: string) => Promise<void>;
  registerError: string | null;
  isRegistering: boolean;
  updateNotificationMode: (mode: NotificationMode) => Promise<void>;
}

/**
 * Kullanıcının buzdolabı profilini yönetir. Veri buzdolabı bazında
 * partition'landığı için (hane modeli), profil kaydı OLMADAN hiçbir veri
 * isteği anlamlı değildir — backend bunu 409 `profile_required` ile
 * reddeder. Bu hook o adımı arayüz tarafında görünür kılar.
 */
export function useProfile(config: ApiConfig, enabled: boolean): UseProfileResult {
  const [profile, setProfile] = useState<UserProfileDto | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [needsRegistration, setNeedsRegistration] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isRegistering, setIsRegistering] = useState(false);
  const [registerError, setRegisterError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    getMe(config)
      .then((p) => {
        if (cancelled) return;
        setProfile(p);
        setNeedsRegistration(false);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiRequestError && err.status === 404) {
          setNeedsRegistration(true);
        } else {
          setError(err instanceof Error ? err.message : "Profil alınamadı");
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [config, enabled]);

  const register = useCallback(
    async (displayName: string, fridgeId: string) => {
      setIsRegistering(true);
      setRegisterError(null);
      try {
        const p = await registerProfile(config, {
          display_name: displayName,
          fridge_id: fridgeId,
        });
        setProfile(p);
        setNeedsRegistration(false);
      } catch (err) {
        setRegisterError(
          err instanceof ApiRequestError && err.status === 400
            ? "Geçersiz buzdolabı ID'si. Lütfen size verilen ID'yi kontrol edin."
            : err instanceof Error
              ? err.message
              : "Kayıt oluşturulamadı",
        );
        throw err;
      } finally {
        setIsRegistering(false);
      }
    },
    [config],
  );

  const updateNotificationMode = useCallback(
    async (mode: NotificationMode) => {
      if (!profile) return;
      const updated = await putNotificationPreferences(config, {
        ...profile.notification_preferences,
        mode,
      });
      setProfile((prev) => (prev ? { ...prev, notification_preferences: updated } : prev));
    },
    [config, profile],
  );

  return {
    profile,
    isLoading,
    needsRegistration,
    error,
    register,
    registerError,
    isRegistering,
    updateNotificationMode,
  };
}
