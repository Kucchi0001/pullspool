import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { api } from "@/services/api";
import type { ServerInfo, User } from "@/services/types";

export const useAuthStore = defineStore("auth", () => {
  const user = ref<User | null>(null);
  const server = ref<ServerInfo | null>(null);
  const ready = ref(false);
  const loading = ref(false);

  const isAuthenticated = computed(() => user.value !== null);
  const mustChangePassword = computed(() => user.value?.must_change_password === true);

  async function bootstrap(): Promise<void> {
    try {
      const me = await api.auth.me();
      user.value = me.user;
      server.value = me.server;
    } catch {
      user.value = null;
      server.value = null;
    } finally {
      ready.value = true;
    }
  }

  async function login(username: string, password: string): Promise<User> {
    loading.value = true;
    try {
      const result = await api.auth.login(username, password);
      user.value = result.user;
      const me = await api.auth.me();
      server.value = me.server;
      user.value = me.user;
      return me.user;
    } finally {
      loading.value = false;
    }
  }

  async function logout(): Promise<void> {
    try {
      await api.auth.logout();
    } catch {
      // Session may already be gone; the local state is what matters.
    }
    user.value = null;
    server.value = null;
  }

  async function changeUsername(newUsername: string, currentPassword: string): Promise<User> {
    const updated = await api.auth.changeUsername(newUsername, currentPassword);
    user.value = updated;
    return updated;
  }

  async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
    await api.auth.changePassword(currentPassword, newPassword);
    if (user.value) {
      user.value = { ...user.value, must_change_password: false };
    }
  }

  async function refreshMe(): Promise<void> {
    const me = await api.auth.me();
    user.value = me.user;
    server.value = me.server;
  }

  return {
    user,
    server,
    ready,
    loading,
    isAuthenticated,
    mustChangePassword,
    bootstrap,
    login,
    logout,
    changePassword,
    changeUsername,
    refreshMe,
  };
});
