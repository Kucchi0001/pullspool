import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { api } from "@/services/api";
import type { Counts, CreateTaskPayload, Task } from "@/services/types";

const EMPTY_COUNTS: Counts = {
  downloading: 0,
  queued: 0,
  paused: 0,
  verifying: 0,
  ready: 0,
  failed: 0,
  canceled: 0,
  total: 0,
};

export const useTasksStore = defineStore("tasks", () => {
  const active = ref<Task[]>([]);
  const ready = ref<Task[]>([]);
  const history = ref<Task[]>([]);
  const downloads = ref<Task[]>([]);
  const counts = ref<Counts>({ ...EMPTY_COUNTS });
  const loading = ref(false);
  const historyTotal = ref(0);
  const readyTotal = ref(0);
  const activeTotal = ref(0);
  let refreshTimer: number | null = null;

  const totalRunning = computed(
    () => counts.value.downloading + counts.value.verifying + counts.value.queued,
  );

  async function fetchActive(): Promise<void> {
    const page = await api.tasks.list({ scope: "active", page_size: 100, sort: "created_at" });
    active.value = page.items;
    activeTotal.value = page.total;
    counts.value = page.counts;
  }

  async function fetchReady(): Promise<void> {
    const page = await api.tasks.list({
      scope: "ready",
      page_size: 100,
      sort: "completed_at",
      order: "desc",
    });
    ready.value = page.items;
    readyTotal.value = page.total;
    counts.value = page.counts;
  }

  async function fetchHistory(): Promise<void> {
    const page = await api.tasks.list({
      scope: "history",
      page_size: 100,
      sort: "created_at",
      order: "desc",
    });
    history.value = page.items;
    historyTotal.value = page.total;
  }

  async function fetchDownloads(): Promise<void> {
    const page = await api.tasks.list({
      scope: "all",
      page_size: 100,
      sort: "created_at",
      order: "desc",
    });
    downloads.value = page.items.filter(
      (task) => task.status !== "completed" && task.deleted_at === null,
    );
    counts.value = page.counts;
  }

  async function refreshAll(): Promise<void> {
    loading.value = true;
    try {
      await Promise.all([fetchActive(), fetchReady(), fetchHistory(), fetchDownloads()]);
    } finally {
      loading.value = false;
    }
  }

  function scheduleRefresh(delay = 350): void {
    if (refreshTimer !== null) window.clearTimeout(refreshTimer);
    refreshTimer = window.setTimeout(() => {
      refreshTimer = null;
      void refreshAll();
    }, delay);
  }

  function upsert(task: Task): void {
    const apply = (list: Task[]) => {
      const index = list.findIndex((item) => item.id === task.id);
      if (index >= 0) list.splice(index, 1, task);
    };
    apply(active.value);
    apply(ready.value);
    apply(history.value);
    apply(downloads.value);
  }

  function removeTask(task: Task): void {
    const strip = (list: Task[]) => list.filter((item) => item.id !== task.id);
    active.value = strip(active.value);
    ready.value = strip(ready.value);
    history.value = strip(history.value);
    downloads.value = strip(downloads.value);
  }

  async function create(payload: CreateTaskPayload): Promise<{ task: Task; duplicate: boolean }> {
    const result = await api.tasks.create(payload);
    scheduleRefresh(100);
    return result;
  }

  async function pause(task: Task): Promise<void> {
    const result = await api.tasks.pause(task.id);
    upsert(result.task);
  }

  async function resume(task: Task): Promise<void> {
    const result = await api.tasks.resume(task.id);
    upsert(result.task);
  }

  async function cancel(task: Task, deleteFiles: boolean): Promise<void> {
    const result = await api.tasks.cancel(task.id, deleteFiles);
    upsert(result.task);
    scheduleRefresh(200);
  }

  async function retry(task: Task): Promise<void> {
    const result = await api.tasks.retry(task.id);
    upsert(result.task);
    scheduleRefresh(200);
  }

  async function remove(task: Task, deleteFiles: boolean): Promise<void> {
    await api.tasks.remove(task.id, deleteFiles);
    removeTask(task);
    scheduleRefresh(200);
  }

  async function acknowledge(task: Task): Promise<void> {
    const result = await api.tasks.ack(task.id);
    upsert(result.task);
    scheduleRefresh(200);
  }

  async function downloadToken(task: Task): Promise<string> {
    const token = await api.tasks.token(task.id);
    return token.url;
  }

  return {
    active,
    ready,
    history,
    downloads,
    counts,
    loading,
    activeTotal,
    readyTotal,
    historyTotal,
    totalRunning,
    fetchActive,
    fetchReady,
    fetchHistory,
    fetchDownloads,
    refreshAll,
    scheduleRefresh,
    upsert,
    removeTask,
    create,
    pause,
    resume,
    cancel,
    retry,
    remove,
    acknowledge,
    downloadToken,
  };
});
