/**
 * H4 拆分：提醒通知 toast。
 *
 * Presentational 组件 — 仅接收 alarms 数组，不持有状态。
 */
export interface Alarm {
  message: string;
  triggeredAt: string;
}

export interface AlarmNotificationsProps {
  alarms: Alarm[];
}

export function AlarmNotifications({ alarms }: AlarmNotificationsProps) {
  if (alarms.length === 0) return null;

  return (
    <div className="fixed top-4 right-4 z-50 space-y-2">
      {alarms.map((alarm, index) => (
        <div
          key={index}
          className="bg-[var(--color-accent)] text-white px-4 py-3 rounded-lg shadow-lg animate-slide-in max-w-sm"
        >
          <div className="flex items-center gap-2">
            <svg
              className="w-5 h-5 flex-shrink-0"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
              />
            </svg>
            <div>
              <p className="font-medium">提醒</p>
              <p className="text-sm opacity-90">{alarm.message}</p>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
