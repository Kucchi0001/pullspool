import { defineStore } from "pinia";
import { ref } from "vue";

import { api } from "@/services/api";
import type { SettingsResponse, StorageResponse, SystemStatus, TrafficResponse } from "@/services/types";

export const useSystemStore = defineStore("system", () => {
  const status = ref<SystemStatus | null>(null);
  const traffic = ref<TrafficResponse | null>(null);
  const storage = ref<StorageResponse | null>(null);
  const statusError = ref<string | null>(null);
  let timer: number | null = null;

  async function refreshStatus(): Promise<void> {
    try {
      status.value = await api.system.status();
      statusError.value = null;
    } catch (error) {
      statusError.value = error instanceof Error ? error.message : "状态获取失败";
    }
  }

  async function refreshTraffic(days = 14): Promise<void> {
    try {
      traffic.value = await api.system.traffic(days);
    } catch {
      // keep the previous series; traffic is advisory
    }
  }

  async function refreshStorage(): Promise<void> {
    try {
      storage.value = await api.system.storage();
    } catch {
      // ignore
    }
  }

  async function refreshAll(): Promise<void> {
    await Promise.all([refreshStatus(), refreshTraffic(), refreshStorage()]);
  }

  function startPolling(intervalMs = 10_000): void {
    stopPolling();
    timer = window.setInterval(() => {
      void refreshStatus();
      void refreshTraffic();
    }, intervalMs);
  }

  function stopPolling(): void {
    if (timer !== null) {
      window.clearInterval(timer);
      timer = null;
    }
  }

  const settings = ref<SettingsResponse | null>(null);

  async function loadSettings(): Promise<SettingsResponse> {
    const result = await api.settings.get();
    settings.value = result;
    return result;
  }

  return {
    status,
    traffic,
    storage,
    settings,
    statusError,
    refreshStatus,
    refreshTraffic,
    refreshStorage,
    refreshAll,
    startPolling,
    stopPolling,
    loadSettings,
  };
});
