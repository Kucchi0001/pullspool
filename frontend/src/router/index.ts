import { createRouter, createWebHistory } from "vue-router";

import { useAuthStore } from "@/stores/auth";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/login",
      name: "login",
      component: () => import("@/views/LoginView.vue"),
      meta: { public: true },
    },
    {
      path: "/change-password",
      name: "change-password",
      component: () => import("@/views/ChangePasswordView.vue"),
    },
    {
      path: "/",
      name: "overview",
      component: () => import("@/views/OverviewView.vue"),
      meta: { title: "总览" },
    },
    {
      path: "/downloads",
      name: "downloads",
      component: () => import("@/views/DownloadsView.vue"),
      meta: { title: "下载" },
    },
    {
      path: "/ready",
      name: "ready",
      component: () => import("@/views/ReadyView.vue"),
      meta: { title: "等待取回" },
    },
    {
      path: "/history",
      name: "history",
      component: () => import("@/views/HistoryView.vue"),
      meta: { title: "历史" },
    },
    {
      path: "/settings",
      name: "settings",
      component: () => import("@/views/SettingsView.vue"),
      meta: { title: "设置" },
    },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
  scrollBehavior: () => ({ top: 0 }),
});

router.beforeEach(async (to) => {
  const auth = useAuthStore();
  if (!auth.ready) {
    await auth.bootstrap();
  }

  if (to.meta.public) {
    if (auth.user) {
      return { name: auth.mustChangePassword ? "change-password" : "overview" };
    }
    return true;
  }

  if (!auth.user) {
    return { name: "login", query: to.fullPath === "/" ? {} : { next: to.fullPath } };
  }

  if (auth.mustChangePassword && to.name !== "change-password") {
    return { name: "change-password" };
  }
  if (!auth.mustChangePassword && to.name === "change-password") {
    return { name: "overview" };
  }
  return true;
});

export default router;
