<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import AppIcon from "@/components/AppIcon.vue";
import BrandLogo from "@/components/BrandLogo.vue";
import NewTaskDrawer from "@/components/NewTaskDrawer.vue";
import { useEvents } from "@/composables/useEvents";
import { useAuthStore } from "@/stores/auth";
import { useSystemStore } from "@/stores/system";
import { useTasksStore } from "@/stores/tasks";
import { useUiStore } from "@/stores/ui";

const props = defineProps<{ title: string }>();

const auth = useAuthStore();
const tasks = useTasksStore();
const system = useSystemStore();
const ui = useUiStore();
const router = useRouter();
const route = useRoute();

useEvents();

const sidebarOpen = ref(false);
let pollTimer: number | null = null;

const nav = computed(() => [
  { name: "overview", label: "总览", icon: "grid", count: 0 },
  {
    name: "downloads",
    label: "下载",
    icon: "download",
    count: tasks.counts.downloading + tasks.counts.queued + tasks.counts.paused,
  },
  { name: "ready", label: "等待取回", icon: "inbox", count: tasks.counts.ready },
  { name: "history", label: "历史", icon: "clock", count: 0 },
  { name: "settings", label: "设置", icon: "sliders", count: 0 },
]);

const themeIcon = computed(() =>
  ui.theme === "system" ? "monitor" : ui.theme === "dark" ? "moon" : "sun",
);

const themeLabel = computed(() =>
  ui.theme === "system" ? "跟随系统" : ui.theme === "dark" ? "深色主题" : "浅色主题",
);

const drawerOpen = computed({
  get: () => ui.newTaskOpen,
  set: (value: boolean) => {
    if (value) ui.openNewTask();
    else ui.closeNewTask();
  },
});

function cycleTheme(): void {
  ui.setTheme(ui.theme === "system" ? "light" : ui.theme === "light" ? "dark" : "system");
}

async function refresh(): Promise<void> {
  try {
    await Promise.all([tasks.refreshAll(), system.refreshStatus()]);
  } catch {
    // A refresh failing should not interrupt the page; SSE/polling will retry.
  }
}

async function signOut(): Promise<void> {
  await auth.logout();
  await router.push({ name: "login" });
}

function onTaskCreated(): void {
  tasks.scheduleRefresh(100);
}

onMounted(async () => {
  await refresh();
  void system.refreshTraffic();
  system.startPolling(12_000);
  pollTimer = window.setInterval(() => {
    if (!ui.sseConnected) void refresh();
  }, 15_000);
});

onBeforeUnmount(() => {
  system.stopPolling();
  if (pollTimer !== null) window.clearInterval(pollTimer);
});

function go(name: string): void {
  sidebarOpen.value = false;
  if (route.name !== name) void router.push({ name });
}
</script>

<template>
  <a class="skip" href="#main-content">跳到主要内容</a>
  <div class="shell">
    <aside class="sidebar" :class="{ open: sidebarOpen }">
      <div class="brand">
        <BrandLogo :size="38" />
        <span class="brand-copy">
          <span class="brand-text">PullSpool</span>
          <span class="brand-sub">SELF-HOSTED</span>
        </span>
      </div>

      <button type="button" class="cta" @click="ui.openNewTask()">
        <span class="cta-icon"><AppIcon name="plus" :size="15" :stroke-width="2" /></span>
        <span class="cta-label">新建下载</span>
      </button>

      <p class="nav-caption">工作区</p>
      <nav class="nav" aria-label="主导航">
        <button
          v-for="item in nav"
          :key="item.name"
          type="button"
          class="nav-item"
          :class="{ active: route.name === item.name }"
          :title="item.label"
          @click="go(item.name)"
        >
          <AppIcon :name="item.icon" :size="17" :stroke-width="1.7" />
          <span class="nav-label">{{ item.label }}</span>
          <span v-if="item.count > 0" class="nav-count num">{{ item.count }}</span>
        </button>
      </nav>

      <div class="sidebar-footer">
        <button type="button" class="footer-item" :title="themeLabel" @click="cycleTheme">
          <AppIcon :name="themeIcon" :size="16" :stroke-width="1.7" />
          <span class="footer-label">{{ themeLabel }}</span>
        </button>
        <div class="user">
          <span class="avatar">{{ (auth.user?.username ?? "?").slice(0, 1).toUpperCase() }}</span>
          <span class="user-copy">
            <span class="user-name">{{ auth.user?.username }}</span>
            <span class="user-role">管理员</span>
          </span>
          <button type="button" class="logout" title="退出登录" aria-label="退出登录" @click="signOut">
            <AppIcon name="logout" :size="15" :stroke-width="1.7" />
          </button>
        </div>
      </div>
    </aside>

    <Transition name="backdrop">
      <div v-if="sidebarOpen" class="sidebar-backdrop" @click="sidebarOpen = false" />
    </Transition>

    <div class="main">
      <header class="topbar">
        <div class="topbar-inner">
          <button type="button" class="menu" aria-label="打开导航" @click="sidebarOpen = true">
            <AppIcon name="menu" :size="18" :stroke-width="1.8" />
          </button>
          <div class="title-wrap">
            <h1 class="page-title">{{ props.title }}</h1>
            <span class="title-meta">
              <span class="live" :class="{ connected: ui.sseConnected }" :title="ui.sseConnected ? '实时推送已连接' : '使用轮询刷新'">
                <span class="live-dot" />
                {{ ui.sseConnected ? "实时" : "轮询" }}
              </span>
            </span>
          </div>
          <div class="topbar-right">
            <span class="live-pill" :class="{ connected: ui.sseConnected }">
              <span class="live-dot" />
              {{ ui.sseConnected ? "实时连接" : "轮询中" }}
            </span>
            <button type="button" class="icon-btn" aria-label="刷新" title="刷新" @click="refresh">
              <AppIcon name="refresh" :size="16" :stroke-width="1.8" />
            </button>
          </div>
        </div>
      </header>

      <main id="main-content" class="content">
        <div class="content-inner">
          <div :key="route.path" class="view">
            <slot />
          </div>
        </div>
      </main>
    </div>

    <nav class="bottom-nav" aria-label="移动端导航">
      <button
        v-for="item in nav"
        :key="item.name"
        type="button"
        class="bottom-item"
        :class="{ active: route.name === item.name }"
        @click="go(item.name)"
      >
        <span class="bottom-icon">
          <AppIcon :name="item.icon" :size="18" :stroke-width="1.75" />
          <span v-if="item.count > 0" class="bottom-count num">{{ item.count }}</span>
        </span>
        <span class="bottom-label">{{ item.label }}</span>
      </button>
    </nav>

    <NewTaskDrawer v-model="drawerOpen" @created="onTaskCreated" />
  </div>
</template>

<style scoped>
.skip {
  position: fixed;
  left: 12px;
  top: -60px;
  z-index: 100;
  padding: 8px 14px;
  border-radius: var(--radius-md);
  background: var(--bg-raised);
  border: 1px solid var(--border);
  color: var(--text-primary);
  transition: top 160ms var(--ease-out);
}
.skip:focus {
  top: 12px;
}

.shell {
  display: flex;
  min-height: 100dvh;
  background-color: var(--bg-canvas);
  background-image: linear-gradient(
    90deg,
    var(--sidebar-bg) 0,
    var(--sidebar-bg) var(--sidebar-w),
    transparent var(--sidebar-w)
  );
}

/* --------------------------------------------------------------- sidebar */
.sidebar {
  position: sticky;
  top: 0;
  z-index: 40;
  display: flex;
  flex-direction: column;
  flex: none;
  width: var(--sidebar-w);
  height: 100dvh;
  padding: 22px 14px 14px;
  background: var(--sidebar-bg);
  color: var(--sidebar-text);
  border-right: 1px solid var(--sidebar-border);
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 10px;
  margin-bottom: 22px;
}

.brand-copy {
  display: flex;
  flex-direction: column;
  line-height: 1.15;
  min-width: 0;
}

.brand-text {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--sidebar-text-strong);
}

.brand-sub {
  margin-top: 3px;
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.14em;
  color: var(--sidebar-muted);
}

.cta {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  height: var(--cta-h);
  padding: 0 10px;
  margin-bottom: 24px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 11px;
  background: var(--accent);
  color: var(--accent-contrast);
  font-size: var(--fs-sm);
  font-weight: 550;
  cursor: pointer;
  transition: background var(--duration) var(--ease-out), transform var(--duration) var(--ease-out);
}

.cta:hover {
  background: var(--accent-hover);
}

.cta:active {
  transform: scale(0.985);
}

.cta-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.16);
}

.nav-caption {
  padding: 0 10px;
  margin-bottom: 8px;
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: var(--sidebar-muted);
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-item::before {
  content: "";
  position: absolute;
  left: 0;
  top: 11px;
  bottom: 11px;
  width: 2px;
  border-radius: 2px;
  background: var(--accent);
  transform: scaleY(0);
  transition: transform 200ms var(--ease-out);
}

.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 11px;
  width: 100%;
  height: var(--nav-item-h);
  padding: 0 10px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: var(--sidebar-text);
  font-size: var(--fs-sm);
  text-align: left;
  cursor: pointer;
  transition: background var(--duration) var(--ease-out), color var(--duration) var(--ease-out);
}

.nav-item svg {
  transition: transform 180ms var(--ease-out);
}

.nav-item:hover {
  background: var(--sidebar-hover);
  color: var(--sidebar-text-strong);
}

.nav-item:hover svg,
.nav-item.active svg {
  transform: translateX(1px);
}

.nav-item.active {
  background: var(--sidebar-active);
  color: var(--sidebar-text-strong);
  font-weight: 550;
}

.nav-item.active::before {
  transform: scaleY(1);
}

.nav-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nav-count {
  min-width: 20px;
  height: 18px;
  padding: 0 6px;
  border-radius: var(--radius-pill);
  background: rgba(255, 255, 255, 0.07);
  color: var(--sidebar-text);
  font-size: 10.5px;
  line-height: 18px;
  text-align: center;
}

.nav-item.active .nav-count {
  background: var(--accent);
  color: var(--accent-contrast);
}

.sidebar-footer {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-top: 12px;
  border-top: 1px solid var(--sidebar-border);
}

.footer-item {
  display: flex;
  align-items: center;
  gap: 11px;
  height: 36px;
  padding: 0 10px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: var(--sidebar-text);
  font-size: var(--fs-sm);
  cursor: pointer;
}

.footer-item:hover {
  background: var(--sidebar-hover);
  color: var(--sidebar-text-strong);
}

.footer-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px 4px;
}

.avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 30px;
  height: 30px;
  border-radius: 10px;
  background: var(--sidebar-surface);
  border: 1px solid var(--sidebar-border);
  color: var(--sidebar-text-strong);
  font-size: 11.5px;
  font-weight: 600;
}

.user-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.25;
}

.user-name {
  font-size: 12.5px;
  font-weight: 550;
  color: var(--sidebar-text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-role {
  font-size: 10px;
  color: var(--sidebar-muted);
}

.logout {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  margin-left: auto;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--sidebar-muted);
  cursor: pointer;
}

.logout:hover {
  background: var(--sidebar-hover);
  color: var(--sidebar-text-strong);
}

/* ------------------------------------------------------------------ main */
.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.topbar-inner {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  max-width: calc(var(--content-max) + var(--page-pad) * 2);
  margin: 0 auto;
  padding: 0 var(--page-pad);
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 30;
  display: flex;
  align-items: center;
  gap: 12px;
  height: var(--topbar-h);
  padding: 0;
  background: color-mix(in srgb, var(--bg-canvas) 86%, transparent);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid transparent;
  transition: border-color var(--duration) var(--ease-out);
}

@supports (position: sticky) {
  .topbar {
    border-bottom-color: var(--border-subtle);
  }
}

.menu {
  display: none;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-surface);
  color: var(--text-secondary);
  cursor: pointer;
}

.title-wrap {
  display: flex;
  align-items: baseline;
  gap: 12px;
  min-width: 0;
}

.title-meta {
  display: none;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
}

.live-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  background: var(--bg-surface);
  color: var(--text-tertiary);
  font-size: 11px;
  font-weight: 500;
}

.live-pill.connected {
  color: var(--text-secondary);
}

.live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--warning);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--warning) 14%, transparent);
}

.live-pill.connected .live-dot,
.live.connected .live-dot {
  background: var(--success);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--success) 14%, transparent);
  animation: live-pulse 2.6s var(--ease-out) infinite;
}

@keyframes live-pulse {
  0% {
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--success) 18%, transparent);
  }
  70% {
    box-shadow: 0 0 0 8px color-mix(in srgb, var(--success) 0%, transparent);
  }
  100% {
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--success) 18%, transparent);
  }
}

.live {
  display: none;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-tertiary);
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-surface);
  color: var(--text-secondary);
  cursor: pointer;
  transition: background var(--duration) var(--ease-out), color var(--duration) var(--ease-out),
    transform var(--duration) var(--ease-out);
}

.icon-btn:hover {
  background: var(--bg-raised);
  color: var(--text-primary);
}

.icon-btn:active {
  transform: scale(0.96);
}

.content {
  flex: 1;
  min-width: 0;
  padding: 24px var(--page-pad) 48px;
}

.bottom-nav {
  display: none;
}

.content-inner {
  width: 100%;
  max-width: var(--content-max);
  margin: 0 auto;
}

/* ------------------------------------------------------------ responsive */
@media (max-width: 1180px) {
  .shell {
    background-image: linear-gradient(
      90deg,
      var(--sidebar-bg) 0,
      var(--sidebar-bg) var(--sidebar-w-collapsed),
      transparent var(--sidebar-w-collapsed)
    );
  }
  .sidebar {
    width: var(--sidebar-w-collapsed);
    padding: 18px 10px 12px;
  }
  .brand {
    justify-content: center;
    padding: 0;
  }
  .brand-copy,
  .cta-label,
  .nav-label,
  .footer-label,
  .user-copy {
    display: none;
  }
  .cta {
    justify-content: center;
    padding: 0;
  }
  .cta-icon {
    background: transparent;
  }
  .nav-caption {
    text-align: center;
    padding: 0;
    font-size: 8px;
    letter-spacing: 0.08em;
  }
  .nav-item,
  .footer-item {
    justify-content: center;
    padding: 0;
    gap: 0;
  }
  .nav-count {
    position: absolute;
    top: 3px;
    right: 4px;
    min-width: 15px;
    height: 15px;
    padding: 0 3px;
    font-size: 9px;
    line-height: 15px;
  }
  .nav-item.active::before {
    top: 10px;
    bottom: 10px;
  }
  .user {
    justify-content: center;
    padding: 8px 0 2px;
  }
  .logout {
    display: none;
  }
}

@media (max-width: 767px) {
  .shell {
    background-image: none;
  }
  .sidebar {
    position: fixed;
    left: 0;
    top: 0;
    z-index: 60;
    display: flex;
    width: 264px;
    padding: 20px 14px 14px;
    transform: translateX(-100%);
    transition: transform 240ms var(--ease-out);
    box-shadow: var(--shadow-modal);
  }
  .sidebar.open {
    transform: translateX(0);
  }
  .sidebar .brand-copy,
  .sidebar .cta-label,
  .sidebar .nav-label,
  .sidebar .footer-label,
  .sidebar .user-copy {
    display: block;
  }
  .sidebar .brand-copy {
    display: flex;
    flex-direction: column;
  }
  .sidebar .user-copy {
    display: flex;
    flex-direction: column;
  }
  .sidebar .brand {
    justify-content: flex-start;
    padding: 0 8px;
  }
  .sidebar .cta {
    justify-content: flex-start;
    padding: 0 10px;
  }
  .sidebar .nav-item,
  .sidebar .footer-item {
    justify-content: flex-start;
    padding: 0 10px;
    gap: 11px;
  }
  .sidebar .nav-count {
    position: static;
    min-width: 20px;
    height: 18px;
    font-size: 10.5px;
    line-height: 18px;
  }
  .sidebar .user {
    justify-content: flex-start;
    padding: 8px 8px 4px;
  }
  .sidebar .logout {
    display: inline-flex;
  }

  .sidebar-backdrop {
    position: fixed;
    inset: 0;
    z-index: 55;
    background: var(--overlay);
    backdrop-filter: blur(2px);
  }

  .menu {
    display: inline-flex;
  }

  .topbar {
    height: 58px;
    padding: 0;
  }
  .topbar-inner {
    gap: 10px;
    padding: 0 16px;
  }

  .page-title {
    font-size: 19px;
  }

  .topbar-right {
    gap: 8px;
  }

  .live-pill {
    display: none;
  }

  .title-meta {
    display: inline-flex;
  }

  .live {
    display: inline-flex;
  }

  .content {
    padding: 12px 16px 92px;
  }

  .bottom-nav {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 45;
    display: flex;
    align-items: stretch;
    height: 62px;
    padding: 6px 6px calc(6px + env(safe-area-inset-bottom));
    background: color-mix(in srgb, var(--bg-surface) 92%, transparent);
    backdrop-filter: blur(14px);
    border-top: 1px solid var(--border-subtle);
  }

  .bottom-item {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 3px;
    border: 0;
    background: transparent;
    color: var(--text-tertiary);
    font-size: 10px;
    cursor: pointer;
  }

  .bottom-icon {
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 38px;
    height: 24px;
    border-radius: var(--radius-pill);
    transition: background var(--duration) var(--ease-out), color var(--duration) var(--ease-out);
  }

  .bottom-item.active {
    color: var(--accent);
    font-weight: 550;
  }

  .bottom-item.active .bottom-icon {
    background: var(--accent-soft);
  }

  .bottom-count {
    position: absolute;
    top: -4px;
    right: 2px;
    min-width: 15px;
    height: 15px;
    padding: 0 4px;
    border-radius: var(--radius-pill);
    background: var(--brand);
    color: var(--brand-contrast);
    font-size: 9px;
    line-height: 15px;
    text-align: center;
  }
}

.backdrop-enter-active,
.backdrop-leave-active {
  transition: opacity 200ms var(--ease-out);
}
.backdrop-enter-from,
.backdrop-leave-to {
  opacity: 0;
}

@media (min-width: 2200px) {
  .brand {
    --brand-logo-h: 44px;
  }
  .sidebar {
    padding: 26px 18px 16px;
  }
  .brand {
    padding: 0 12px;
    margin-bottom: 26px;
  }
  .brand-text {
    font-size: 16px;
  }
  .brand-sub {
    font-size: 9.5px;
  }
  .cta {
    margin-bottom: 26px;
  }
  .icon-btn {
    width: 36px;
    height: 36px;
  }
  .live-pill {
    height: 34px;
  }
}

@media (min-width: 3000px) {
  .brand {
    --brand-logo-h: 50px;
  }
  .sidebar {
    padding: 30px 20px 18px;
  }
  .brand-text {
    font-size: 17px;
  }
  .icon-btn {
    width: 40px;
    height: 40px;
  }
  .live-pill {
    height: 36px;
  }
}

@media (min-width: 3600px) {
  .brand {
    --brand-logo-h: 54px;
  }
  .sidebar {
    padding: 34px 22px 20px;
  }
  .brand-text {
    font-size: 18px;
  }
  .icon-btn {
    width: 44px;
    height: 44px;
  }
}

@media (min-width: 2200px) {
  .content {
    padding-top: 32px;
  }
}

@media (min-width: 3000px) {
  .content {
    padding-top: 40px;
  }
}

@media (min-width: 3600px) {
  .content {
    padding-top: 48px;
  }
}
</style>