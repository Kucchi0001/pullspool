import { onBeforeUnmount, onMounted, ref } from "vue";

import type { Task } from "@/services/types";
import { useAuthStore } from "@/stores/auth";
import { useSystemStore } from "@/stores/system";
import { useTasksStore } from "@/stores/tasks";
import { useUiStore } from "@/stores/ui";

const EVENT_TYPES = [
  "task.created",
  "task.updated",
  "task.deleted",
  "traffic.updated",
  "system.updated",
  "alert",
] as const;

export function useEvents() {
  const connected = ref(false);
  const tasks = useTasksStore();
  const system = useSystemStore();
  const ui = useUiStore();
  const auth = useAuthStore();

  let source: EventSource | null = null;
  let retryTimer: number | null = null;
  let taskTimer: number | null = null;
  let trafficTimer: number | null = null;

  function scheduleTasks(delay = 2000): void {
    if (taskTimer !== null) window.clearTimeout(taskTimer);
    taskTimer = window.setTimeout(() => {
      taskTimer = null;
      void tasks.refreshAll();
    }, delay);
  }

  function scheduleTraffic(): void {
    if (trafficTimer !== null) window.clearTimeout(trafficTimer);
    trafficTimer = window.setTimeout(() => {
      trafficTimer = null;
      void system.refreshTraffic();
      void system.refreshStatus();
    }, 3000);
  }

  function handle(type: string, payload: Record<string, unknown>): void {
    if (type.startsWith("task.")) {
      const task = payload.task as Task | undefined;
      if (task && type !== "task.deleted") tasks.upsert(task);
      if (type === "task.deleted" && task) tasks.removeTask(task);
      scheduleTasks();
      return;
    }
    if (type === "traffic.updated") {
      scheduleTraffic();
      return;
    }
    if (type === "alert") {
      const level = payload.level === "error" ? "error" : payload.level === "warning" ? "warning" : "info";
      ui.notify(level, String(payload.message ?? "系统提示"));
    }
  }

  function connect(): void {
    if (!auth.isAuthenticated || source !== null) return;
    source = new EventSource("/api/events");

    source.addEventListener("open", () => {
      connected.value = true;
      ui.sseConnected = true;
      scheduleTasks(50);
    });

    for (const type of EVENT_TYPES) {
      source.addEventListener(type, (event: MessageEvent<string>) => {
        try {
          handle(type, JSON.parse(event.data) as Record<string, unknown>);
        } catch {
          // Ignore malformed frames; the polling fallback keeps the UI fresh.
        }
      });
    }

    source.addEventListener("error", () => {
      connected.value = false;
      ui.sseConnected = false;
      source?.close();
      source = null;
      if (retryTimer === null) {
        retryTimer = window.setTimeout(() => {
          retryTimer = null;
          connect();
        }, 5000);
      }
    });
  }

  function disconnect(): void {
    source?.close();
    source = null;
    connected.value = false;
    ui.sseConnected = false;
    if (retryTimer !== null) {
      window.clearTimeout(retryTimer);
      retryTimer = null;
    }
    if (taskTimer !== null) {
      window.clearTimeout(taskTimer);
      taskTimer = null;
    }
    if (trafficTimer !== null) {
      window.clearTimeout(trafficTimer);
      trafficTimer = null;
    }
  }

  onMounted(connect);
  onBeforeUnmount(disconnect);

  return { connected, connect, disconnect };
}
