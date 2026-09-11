import type { NotificationMode, UserProfileDto } from "../api/types";
import { notificationModeLabel } from "../lib/labels";

interface AccountBarProps {
  email: string | null;
  profile: UserProfileDto;
  onLogout: () => void;
  onNotificationModeChange: (mode: NotificationMode) => Promise<void>;
}

const MODES: NotificationMode[] = ["DAILY_DIGEST", "CRITICAL_ONLY", "OFF"];

export function AccountBar({ email, profile, onLogout, onNotificationModeChange }: AccountBarProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="min-w-0">
        <p className="truncate font-medium text-slate-800 dark:text-slate-100">
          {profile.display_name}
          {email && <span className="ml-1.5 font-normal text-slate-400">· {email}</span>}
        </p>
        <p className="text-xs text-slate-400">Buzdolabı: {profile.fridge_id}</p>
      </div>
      <div className="flex items-center gap-2">
        <label className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
          Bildirim:
          <select
            value={profile.notification_preferences.mode}
            onChange={(e) => void onNotificationModeChange(e.target.value as NotificationMode)}
            className="rounded-md border border-slate-300 bg-transparent px-1.5 py-1 text-xs dark:border-slate-700"
          >
            {MODES.map((mode) => (
              <option key={mode} value={mode}>
                {notificationModeLabel(mode)}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={onLogout}
          className="rounded-md border border-slate-300 px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          Çıkış yap
        </button>
      </div>
    </div>
  );
}
