export type UiStatus =
  | "downloading"
  | "queued"
  | "paused"
  | "verifying"
  | "transferring"
  | "ready"
  | "retrieved"
  | "deleted"
  | "expired"
  | "failed"
  | "canceled";

export type TaskStatus =
  | "queued"
  | "active"
  | "paused"
  | "verifying"
  | "completed"
  | "failed"
  | "canceled";

export interface Counts {
  downloading: number;
  queued: number;
  paused: number;
  verifying: number;
  ready: number;
  failed: number;
  canceled: number;
  total: number;
}

export interface Task {
  id: string;
  url_display: string;
  filename: string;
  display_name: string | null;
  status: TaskStatus;
  ui_status: UiStatus;
  file_size: number | null;
  downloaded_size: number;
  progress: number | null;
  download_speed: number;
  eta_seconds: number | null;
  sha256: string | null;
  content_type: string | null;
  supports_range: boolean | null;
  error_code: string | null;
  error_message: string | null;
  attempts: number;
  max_connections: number;
  speed_limit_bytes: number;
  download_bytes: number;
  retrieved_bytes: number;
  transfer_count: number;
  is_file_available: boolean;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  retrieved_at: string | null;
  deleted_at: string | null;
  expires_at: string | null;
}

export interface TaskList {
  items: Task[];
  total: number;
  page: number;
  page_size: number;
  counts: Counts;
}

export interface User {
  id: number;
  username: string;
  must_change_password: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface ServerInfo {
  version: string;
  build: string;
  started_at: string;
  uptime_seconds: number;
}

export interface MeResponse {
  user: User;
  server: ServerInfo;
}

export interface LoginResponse {
  user: User;
}

export interface CreateTaskPayload {
  url: string;
  filename?: string | null;
  connections?: number | null;
  speed_limit_kib_per_s?: number | null;
  max_size_bytes?: number | null;
}

export interface RuntimeSettings {
  max_concurrent_downloads: number;
  default_connections: number;
  default_speed_limit_kib_per_s: number;
  global_speed_limit_kib_per_s: number;
  max_file_size_bytes: number;
  max_total_storage_bytes: number;
  min_free_disk_bytes: number;
  queue_max_length: number;
  retention_hours: number;
  orphan_quarantine_hours: number;
  download_token_ttl_seconds: number;
  max_transfer_concurrency: number;
  session_idle_days: number;
  session_absolute_days: number;
  login_max_attempts: number;
  login_window_minutes: number;
  login_lock_minutes: number;
  density: "comfortable" | "compact";
  theme: "system" | "light" | "dark";
  locale: "zh-CN";
}

export interface SettingsMeta {
  storage_root: string;
  storage_subdir: string;
  tls_mode: string;
  public_base_url: string;
  version: string;
  build: string;
  read_only_keys: string[];
}

export interface SettingsResponse {
  settings: RuntimeSettings;
  meta: SettingsMeta;
}

export interface SettingsUpdateResponse {
  settings: RuntimeSettings;
  applied: string[];
}

export interface HostMetrics {
  cpu_percent: number;
  load_1: number | null;
  load_5: number | null;
  load_15: number | null;
  mem_total: number;
  mem_used: number;
  mem_percent: number;
  disk_total: number;
  disk_used: number;
  disk_free: number;
}

export interface SystemStatus {
  server: ServerInfo;
  host: HostMetrics;
  storage: {
    root: string;
    used_bytes: number;
    quota_bytes: number;
    free_bytes: number;
    min_free_bytes: number;
    orphan_count: number;
  };
  aria2: { reachable: boolean; guarded: string; active: number; waiting: number; stopped: number };
  queue: {
    active: number;
    max_concurrent: number;
    paused_reason: string | null;
    transferring: number;
  };
  counts: Counts;
  public_ip: string | null;
}

export interface TrafficDay {
  date: string;
  download_bytes: number;
  upload_bytes: number;
}

export interface TrafficResponse {
  days: TrafficDay[];
  totals: {
    today_download_bytes: number;
    today_upload_bytes: number;
    month_download_bytes: number;
    month_upload_bytes: number;
    all_download_bytes: number;
    all_upload_bytes: number;
  };
  nic: { rx_bytes: number; tx_bytes: number; collected_at: string };
  note: string;
}

export interface StorageResponse {
  root: string;
  total_bytes: number;
  used_bytes: number;
  free_bytes: number;
  downloads_bytes: number;
  quota_bytes: number;
  min_free_bytes: number;
  tasks: { id: string; filename: string; bytes: number }[];
  orphans: { path: string; bytes: number; quarantined_at: number }[];
}

export interface DownloadToken {
  url: string;
  expires_at: string;
  ttl_seconds: number;
}

export interface Integrity {
  task_id: string;
  sha256: string | null;
  file_size: number | null;
  verified_at: string | null;
  expected_sha256: string | null;
  matches_expected: boolean | null;
  note: string;
}

export interface TaskEvent {
  kind: string;
  message: string;
  created_at: string;
}
