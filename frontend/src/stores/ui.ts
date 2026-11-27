import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";

export type ToastLevel = "success" | "error" | "info" | "warning";
export type ThemeMode = "system" | "light" | "dark";
export type Density = "comfortable" | "compact";

export interface Toast {
  id: number;
  level: ToastLevel;
  message: string;
}

const THEME_KEY = "pullspool.theme";
const DENSITY_KEY = "pullspool.density";

function readTheme(): ThemeMode {
  const stored = localStorage.getItem(THEME_KEY);
  return stored === "light" || stored === "dark" || stored === "system" ? stored : "system";
}

function applyTheme(mode: ThemeMode): void {
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const resolved = mode === "system" ? (prefersDark ? "dark" : "light") : mode;
  document.documentElement.dataset.theme = resolved;
}

export const useUiStore = defineStore("ui", () => {
  const theme = ref<ThemeMode>(readTheme());
  const density = ref<Density>(
    localStorage.getItem(DENSITY_KEY) === "compact" ? "compact" : "comfortable",
  );
  const toasts = ref<Toast[]>([]);
  const sseConnected = ref(false);
  const newTaskOpen = ref(false);
  let nextToastId = 1;

  function openNewTask(): void {
    newTaskOpen.value = true;
  }

  function closeNewTask(): void {
    newTaskOpen.value = false;
  }

  const isDark = computed(() => document.documentElement.dataset.theme === "dark");

  function notify(level: ToastLevel, message: string, ttl = 3200): void {
    const toast: Toast = { id: nextToastId++, level, message };
    toasts.value.push(toast);
    if (toasts.value.length > 3) toasts.value.shift();
    window.setTimeout(() => dismiss(toast.id), level === "error" ? 5200 : ttl);
  }

  function dismiss(id: number): void {
    toasts.value = toasts.value.filter((toast) => toast.id !== id);
  }

  function setTheme(mode: ThemeMode): void {
    theme.value = mode;
  }

  function setDensity(mode: Density): void {
    density.value = mode;
  }

  watch(
    theme,
    (mode) => {
      localStorage.setItem(THEME_KEY, mode);
      applyTheme(mode);
    },
    { immediate: true },
  );

  watch(
    density,
    (mode) => {
      localStorage.setItem(DENSITY_KEY, mode);
      document.documentElement.dataset.density = mode;
    },
    { immediate: true },
  );

  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (theme.value === "system") applyTheme("system");
  });

  return {
    theme,
    density,
    toasts,
    sseConnected,
    newTaskOpen,
    isDark,
    notify,
    dismiss,
    setTheme,
    setDensity,
    openNewTask,
    closeNewTask,
  };
});
