import type {
  CreateTaskPayload,
  DownloadToken,
  Integrity,
  LoginResponse,
  MeResponse,
  RuntimeSettings,
  SettingsResponse,
  SettingsUpdateResponse,
  StorageResponse,
  SystemStatus,
  Task,
  TaskList,
  User,
  TrafficResponse,
} from "./types";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;
  readonly requestId: string;

  constructor(
    message: string,
    code: string,
    status: number,
    details: Record<string, unknown>,
    requestId: string,
  ) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
    this.requestId = requestId;
  }
}

type QueryValue = string | number | boolean | null | undefined;

function query(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers,
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const envelope = (payload as { error?: { code?: string; message?: string; details?: Record<string, unknown>; request_id?: string } })?.error;
    throw new ApiError(
      envelope?.message ?? `请求失败（HTTP ${response.status}）`,
      envelope?.code ?? "INTERNAL_ERROR",
      response.status,
      envelope?.details ?? {},
      envelope?.request_id ?? "",
    );
  }
  return payload as T;
}

export const api = {
  auth: {
    login: (username: string, password: string) =>
      request<LoginResponse>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      }),
    logout: () => request<void>("/api/auth/logout", { method: "POST" }),
    me: () => request<MeResponse>("/api/auth/me"),
    changePassword: (currentPassword: string, newPassword: string) =>
      request<void>("/api/auth/password", {
        method: "POST",
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      }),
    changeUsername: (newUsername: string, currentPassword: string) =>
      request<User>("/api/auth/username", {
        method: "POST",
        body: JSON.stringify({ new_username: newUsername, current_password: currentPassword }),
      }),
  },
  tasks: {
    list: (params: {
      scope?: string;
      status?: string;
      q?: string;
      sort?: string;
      order?: string;
      page?: number;
      page_size?: number;
    }) => request<TaskList>(`/api/tasks${query(params)}`),
    get: (id: string) => request<{ task: Task }>(`/api/tasks/${id}`),
    create: (payload: CreateTaskPayload) =>
      request<{ task: Task; duplicate: boolean }>("/api/tasks", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    pause: (id: string) =>
      request<{ task: Task }>(`/api/tasks/${id}/pause`, { method: "POST" }),
    resume: (id: string) =>
      request<{ task: Task }>(`/api/tasks/${id}/resume`, { method: "POST" }),
    cancel: (id: string, deleteFiles: boolean) =>
      request<{ task: Task }>(`/api/tasks/${id}/cancel`, {
        method: "POST",
        body: JSON.stringify({ delete_files: deleteFiles }),
      }),
    retry: (id: string) =>
      request<{ task: Task }>(`/api/tasks/${id}/retry`, { method: "POST" }),
    remove: (id: string, deleteFiles: boolean) =>
      request<{ task: Task }>(`/api/tasks/${id}${query({ delete_files: deleteFiles })}`, {
        method: "DELETE",
      }),
    ack: (id: string) =>
      request<{ task: Task }>(`/api/tasks/${id}/ack`, {
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      }),
    token: (id: string) =>
      request<DownloadToken>(`/api/tasks/${id}/download-token`, { method: "POST" }),
    integrity: (id: string) => request<Integrity>(`/api/tasks/${id}/integrity`),
    downloadUrl: (id: string) => `/api/tasks/${id}/file`,
  },
  system: {
    status: () => request<SystemStatus>("/api/system/status"),
    storage: () => request<StorageResponse>("/api/system/storage"),
    traffic: (days = 7) => request<TrafficResponse>(`/api/system/traffic${query({ days })}`),
  },
  settings: {
    get: () => request<SettingsResponse>("/api/settings"),
    update: (patch: Partial<RuntimeSettings>) =>
      request<SettingsUpdateResponse>("/api/settings", {
        method: "PUT",
        body: JSON.stringify(patch),
      }),
  },
  health: () => request<{ status: string }>("/api/health"),
};
