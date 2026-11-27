const UNITS = ["B", "KB", "MB", "GB", "TB", "PB"];

export function formatBytes(value: number | null | undefined, digits?: number): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (value <= 0) return "0 B";
  let index = 0;
  let size = value;
  while (size >= 1024 && index < UNITS.length - 1) {
    size /= 1024;
    index += 1;
  }
  const precision = digits ?? (index >= 3 ? 1 : 0);
  return `${size.toFixed(index === 0 ? 0 : precision)} ${UNITS[index]}`;
}

const MB = 1024 * 1024;

/** Traffic totals are always shown in MB (never raw B/KB). */
export function formatTraffic(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value) || value <= 0) return "0 MB";
  const mb = value / MB;
  if (mb < 0.1) return "<0.1 MB";
  if (mb >= 1000) return `${Math.round(mb).toLocaleString("en-US")} MB`;
  if (mb >= 100) return `${Math.round(mb)} MB`;
  if (mb >= 10) return `${Math.round(mb)} MB`;
  return `${mb.toFixed(1)} MB`;
}

export function formatSpeed(bytesPerSecond: number | null | undefined): string {
  if (!bytesPerSecond || bytesPerSecond <= 0) return "—";
  if (bytesPerSecond < 1024 * 1024) {
    return `${Math.round(bytesPerSecond / 1024)} KB/s`;
  }
  return `${(bytesPerSecond / (1024 * 1024)).toFixed(1)} MB/s`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || seconds < 0) return "—";
  if (seconds < 60) return `${Math.round(seconds)} 秒`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    const rest = Math.round(seconds % 60);
    return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 48) {
    const rest = minutes % 60;
    return rest ? `${hours} 小时 ${rest} 分` : `${hours} 小时`;
  }
  return `${Math.floor(hours / 24)} 天`;
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const parsed = new Date(value.endsWith("Z") ? value : `${value}Z`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function pad(value: number): string {
  return value.toString().padStart(2, "0");
}

export function formatDateTime(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) return "—";
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  if (sameDay) return time;
  if (date.getFullYear() === now.getFullYear()) {
    return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${time}`;
  }
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function formatRelative(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) return "—";
  const delta = (Date.now() - date.getTime()) / 1000;
  if (delta < 60) return "刚刚";
  if (delta < 3600) return `${Math.floor(delta / 60)} 分钟前`;
  if (delta < 86400) return `${Math.floor(delta / 3600)} 小时前`;
  if (delta < 86400 * 7) return `${Math.floor(delta / 86400)} 天前`;
  return formatDateTime(value);
}

export function shortSha(value: string | null | undefined, length = 12): string {
  if (!value) return "—";
  return value.length <= length ? value : `${value.slice(0, length)}…`;
}

export function remaining(expiresAt: string | null | undefined): {
  text: string;
  seconds: number | null;
  urgent: boolean;
} {
  const date = parseDate(expiresAt);
  if (!date) return { text: "—", seconds: null, urgent: false };
  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  if (seconds <= 0) return { text: "已过期", seconds: 0, urgent: true };
  return { text: `还剩 ${formatDuration(seconds)}`, seconds, urgent: seconds < 7200 };
}
