<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";

import AppShell from "@/components/AppShell.vue";
import FormField from "@/components/FormField.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import UiButton from "@/components/UiButton.vue";
import { ApiError, api } from "@/services/api";
import { formatBytes } from "@/services/format";
import type { RuntimeSettings, SettingsMeta } from "@/services/types";
import { useAuthStore } from "@/stores/auth";
import { useSystemStore } from "@/stores/system";
import { useUiStore } from "@/stores/ui";

interface FormState {
  max_concurrent_downloads: number;
  default_connections: number;
  default_speed_mbps: number;
  global_speed_mbps: number;
  max_file_size_gb: number;
  max_total_storage_gb: number;
  min_free_disk_gb: number;
  queue_max_length: number;
  retention_hours: number;
  orphan_quarantine_hours: number;
  download_token_ttl_seconds: number;
  max_transfer_concurrency: number;
  session_idle_days: number;
  session_absolute_days: number;
  login_max_attempts: number;
  login_lock_minutes: number;
  theme: "system" | "light" | "dark";
  density: "comfortable" | "compact";
}

const GB = 1024 ** 3;
const auth = useAuthStore();
const system = useSystemStore();
const ui = useUiStore();

const form = ref<FormState | null>(null);
const initial = ref("");
const meta = ref<SettingsMeta | null>(null);
const loading = ref(true);
const saving = ref(false);
const error = ref("");

const password = reactive({ current: "", next: "", confirm: "", error: "", submitting: false });
const username = reactive({ next: "", current: "", error: "", submitting: false });

const dirty = computed(() => form.value !== null && JSON.stringify(form.value) !== initial.value);

const canRename = computed(() => {
  const next = username.next.trim().toLowerCase();
  return next.length > 0 && next !== (auth.user?.username ?? "") && !username.submitting;
});

const storageRatio = computed(() => {
  if (!system.storage || system.storage.quota_bytes <= 0) return null;
  return Math.min(1, system.storage.downloads_bytes / system.storage.quota_bytes);
});

function toForm(settings: RuntimeSettings): FormState {
  return {
    max_concurrent_downloads: settings.max_concurrent_downloads,
    default_connections: settings.default_connections,
    default_speed_mbps: Math.round((settings.default_speed_limit_kib_per_s / 1024) * 10) / 10,
    global_speed_mbps: Math.round((settings.global_speed_limit_kib_per_s / 1024) * 10) / 10,
    max_file_size_gb: Math.round((settings.max_file_size_bytes / GB) * 10) / 10,
    max_total_storage_gb: Math.round((settings.max_total_storage_bytes / GB) * 10) / 10,
    min_free_disk_gb: Math.round((settings.min_free_disk_bytes / GB) * 10) / 10,
    queue_max_length: settings.queue_max_length,
    retention_hours: settings.retention_hours,
    orphan_quarantine_hours: settings.orphan_quarantine_hours,
    download_token_ttl_seconds: settings.download_token_ttl_seconds,
    max_transfer_concurrency: settings.max_transfer_concurrency,
    session_idle_days: settings.session_idle_days,
    session_absolute_days: settings.session_absolute_days,
    login_max_attempts: settings.login_max_attempts,
    login_lock_minutes: settings.login_lock_minutes,
    theme: settings.theme,
    density: settings.density,
  };
}

function toPatch(state: FormState): Partial<RuntimeSettings> {
  return {
    max_concurrent_downloads: Number(state.max_concurrent_downloads),
    default_connections: Number(state.default_connections),
    default_speed_limit_kib_per_s: Math.round(Number(state.default_speed_mbps) * 1024),
    global_speed_limit_kib_per_s: Math.round(Number(state.global_speed_mbps) * 1024),
    max_file_size_bytes: Math.round(Number(state.max_file_size_gb) * GB),
    max_total_storage_bytes: Math.round(Number(state.max_total_storage_gb) * GB),
    min_free_disk_bytes: Math.round(Number(state.min_free_disk_gb) * GB),
    queue_max_length: Number(state.queue_max_length),
    retention_hours: Number(state.retention_hours),
    orphan_quarantine_hours: Number(state.orphan_quarantine_hours),
    download_token_ttl_seconds: Number(state.download_token_ttl_seconds),
    max_transfer_concurrency: Number(state.max_transfer_concurrency),
    session_idle_days: Number(state.session_idle_days),
    session_absolute_days: Number(state.session_absolute_days),
    login_max_attempts: Number(state.login_max_attempts),
    login_lock_minutes: Number(state.login_lock_minutes),
    theme: state.theme,
    density: state.density,
  };
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    const response = await system.loadSettings();
    meta.value = response.meta;
    form.value = toForm(response.settings);
    // Theme/density are per-device preferences: reflect the live UI instead of
    // overwriting it with the value stored on the server.
    form.value.theme = ui.theme;
    form.value.density = ui.density;
    username.next = auth.user?.username ?? "";
    initial.value = JSON.stringify(form.value);
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "设置加载失败";
  } finally {
    loading.value = false;
  }
  void system.refreshStorage();
}

async function save(): Promise<void> {
  if (!form.value) return;
  saving.value = true;
  error.value = "";
  try {
    const result = await api.settings.update(toPatch(form.value));
    if (meta.value) {
      system.settings = { settings: result.settings, meta: meta.value };
    }
    form.value = toForm(result.settings);
    form.value.theme = ui.theme;
    form.value.density = ui.density;
    initial.value = JSON.stringify(form.value);
    ui.notify("success", "设置已保存");
    void system.refreshStatus();
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "保存失败";
    ui.notify("error", error.value);
  } finally {
    saving.value = false;
  }
}

function reset(): void {
  if (!initial.value) return;
  form.value = JSON.parse(initial.value) as FormState;
  if (form.value) {
    ui.setTheme(form.value.theme);
    ui.setDensity(form.value.density);
  }
}

function previewTheme(mode: "system" | "light" | "dark"): void {
  if (!form.value) return;
  form.value.theme = mode;
  ui.setTheme(mode);
}

function previewDensity(mode: "comfortable" | "compact"): void {
  if (!form.value) return;
  form.value.density = mode;
  ui.setDensity(mode);
}

async function saveUsername(): Promise<void> {
  username.error = "";
  const next = username.next.trim().toLowerCase();
  if (!/^[a-z0-9][a-z0-9._-]{2,31}$/.test(next)) {
    username.error = "用户名需为 3–32 位小写字母、数字、点、下划线或连字符，并以字母或数字开头";
    return;
  }
  if (next === auth.user?.username) {
    username.error = "新用户名与当前用户名相同";
    return;
  }
  if (!username.current) {
    username.error = "请输入当前密码以确认";
    return;
  }

  username.submitting = true;
  try {
    const updated = await auth.changeUsername(next, username.current);
    username.next = updated.username;
    username.current = "";
    ui.notify("success", "用户名已更新，下次登录请使用新用户名");
  } catch (caught) {
    username.error = caught instanceof ApiError ? caught.message : "用户名修改失败";
  } finally {
    username.submitting = false;
  }
}

async function changePassword(): Promise<void> {
  password.error = "";
  if (password.next.length < 10) {
    password.error = "新密码至少 10 位，且需包含字母与数字";
    return;
  }
  if (password.next !== password.confirm) {
    password.error = "两次输入的新密码不一致";
    return;
  }
  password.submitting = true;
  try {
    await auth.changePassword(password.current, password.next);
    password.current = "";
    password.next = "";
    password.confirm = "";
    ui.notify("success", "密码已更新");
  } catch (caught) {
    password.error = caught instanceof ApiError ? caught.message : "修改失败";
  } finally {
    password.submitting = false;
  }
}

onMounted(load);
</script>

<template>
  <AppShell title="设置">
    <div v-if="loading" class="loading muted">正在加载设置…</div>

    <div v-else-if="form" class="settings">
      <p v-if="error" class="error-banner" role="alert">{{ error }}</p>

      <section class="panel">
        <header class="panel-header"><span class="section-title">下载</span></header>
        <div class="grid">
          <FormField label="最大并发下载数" hint="同时进行的任务数量，低配 VPS 建议 2。">
            <input v-model.number="form.max_concurrent_downloads" class="input num" type="number" min="1" max="6" />
          </FormField>
          <FormField label="默认连接数" hint="单个任务的分片连接数。">
            <input v-model.number="form.default_connections" class="input num" type="number" min="1" max="16" />
          </FormField>
          <FormField label="默认限速（MB/s）" hint="0 表示不限速（默认）。">
            <input v-model.number="form.default_speed_mbps" class="input num" type="number" min="0" max="1024" step="0.5" />
          </FormField>
          <FormField label="全局限速（MB/s）" hint="0 表示不限速，对所有任务生效。">
            <input v-model.number="form.global_speed_mbps" class="input num" type="number" min="0" max="1024" step="0.5" />
          </FormField>
          <FormField label="单文件大小上限（GB）">
            <input v-model.number="form.max_file_size_gb" class="input num" type="number" min="0.1" max="100" step="0.5" />
          </FormField>
          <FormField label="排队任务上限">
            <input v-model.number="form.queue_max_length" class="input num" type="number" min="1" max="1000" />
          </FormField>
        </div>
      </section>

      <section class="panel">
        <header class="panel-header"><span class="section-title">存储与清理</span></header>
        <div class="grid">
          <FormField label="下载目录" hint="由环境变量决定，界面只读。">
            <input class="input mono" :value="meta?.storage_root" readonly />
          </FormField>
          <FormField label="临时存储配额（GB）">
            <input v-model.number="form.max_total_storage_gb" class="input num" type="number" min="1" max="10240" step="1" />
          </FormField>
          <FormField label="最低剩余磁盘（GB）" hint="低于该值时暂停队列并提示。">
            <input v-model.number="form.min_free_disk_gb" class="input num" type="number" min="0" max="100" step="0.5" />
          </FormField>
          <FormField label="等待取回过期时间（小时）" hint="超时后自动删除临时文件。">
            <input v-model.number="form.retention_hours" class="input num" type="number" min="1" max="720" />
          </FormField>
          <FormField label="孤儿文件隔离时间（小时）">
            <input v-model.number="form.orphan_quarantine_hours" class="input num" type="number" min="1" max="720" />
          </FormField>
          <FormField label="下载令牌有效期（秒）">
            <input v-model.number="form.download_token_ttl_seconds" class="input num" type="number" min="60" max="3600" />
          </FormField>
          <FormField label="同时回传上限">
            <input v-model.number="form.max_transfer_concurrency" class="input num" type="number" min="1" max="4" />
          </FormField>
          <div class="usage">
            <span class="hint">当前临时文件占用</span>
            <span class="num usage-value">
              {{ system.storage ? `${formatBytes(system.storage.downloads_bytes)} / ${formatBytes(system.storage.quota_bytes)}` : "—" }}
            </span>
            <ProgressBar v-if="storageRatio !== null" :value="storageRatio" status="ready" :height="3" />
          </div>
        </div>
      </section>

      <section class="panel">
        <header class="panel-header"><span class="section-title">安全</span></header>
        <div class="grid">
          <FormField label="会话空闲过期（天）">
            <input v-model.number="form.session_idle_days" class="input num" type="number" min="1" max="30" />
          </FormField>
          <FormField label="会话绝对过期（天）">
            <input v-model.number="form.session_absolute_days" class="input num" type="number" min="1" max="180" />
          </FormField>
          <FormField label="登录失败上限（次）">
            <input v-model.number="form.login_max_attempts" class="input num" type="number" min="3" max="20" />
          </FormField>
          <FormField label="登录锁定时长（分钟）">
            <input v-model.number="form.login_lock_minutes" class="input num" type="number" min="1" max="1440" />
          </FormField>
        </div>

        <div class="divider" />
        <div class="username-block">
          <div>
            <p class="block-title">登录用户名</p>
            <p class="hint">
              当前用户名：<strong class="current-name">{{ auth.user?.username }}</strong>。
              修改后当前会话保持有效，下次登录请使用新用户名。
            </p>
          </div>
          <div class="username-grid">
            <input
              v-model="username.next"
              class="input"
              maxlength="32"
              autocomplete="username"
              placeholder="新用户名"
              @keyup.enter="saveUsername"
            />
            <input
              v-model="username.current"
              class="input"
              type="password"
              autocomplete="current-password"
              placeholder="当前密码（确认身份）"
              @keyup.enter="saveUsername"
            />
            <UiButton :loading="username.submitting" :disabled="!canRename" @click="saveUsername">
              更新用户名
            </UiButton>
          </div>
          <p class="hint">3–32 位，小写字母、数字、点、下划线或连字符；需输入当前密码确认。</p>
          <p v-if="username.error" class="error-text">{{ username.error }}</p>
        </div>
        <div class="divider" />
        <div class="password-block">
          <div>
            <p class="block-title">修改登录密码</p>
            <p class="hint">修改成功后，其他设备上的会话会被注销。</p>
          </div>
          <div class="password-grid">
            <input v-model="password.current" class="input" type="password" placeholder="当前密码" autocomplete="current-password" />
            <input v-model="password.next" class="input" type="password" placeholder="新密码（至少 10 位）" autocomplete="new-password" />
            <input v-model="password.confirm" class="input" type="password" placeholder="确认新密码" autocomplete="new-password" />
            <UiButton :loading="password.submitting" @click="changePassword">更新密码</UiButton>
          </div>
          <p v-if="password.error" class="error-text">{{ password.error }}</p>
        </div>
      </section>

      <section class="panel">
        <header class="panel-header"><span class="section-title">界面</span></header>
        <div class="grid">
          <FormField label="主题" hint="跟随系统时自动切换明暗。">
            <div class="segmented">
              <button type="button" :class="{ active: form.theme === 'system' }" @click="previewTheme('system')">跟随系统</button>
              <button type="button" :class="{ active: form.theme === 'light' }" @click="previewTheme('light')">浅色</button>
              <button type="button" :class="{ active: form.theme === 'dark' }" @click="previewTheme('dark')">深色</button>
            </div>
          </FormField>
          <FormField label="列表密度">
            <div class="segmented">
              <button type="button" :class="{ active: form.density === 'comfortable' }" @click="previewDensity('comfortable')">舒适</button>
              <button type="button" :class="{ active: form.density === 'compact' }" @click="previewDensity('compact')">紧凑</button>
            </div>
          </FormField>
          <FormField label="语言">
            <input class="input" value="简体中文" readonly />
          </FormField>
        </div>
      </section>

      <section class="panel">
        <header class="panel-header"><span class="section-title">关于</span></header>
        <div class="about">
          <div><span class="muted">版本</span><span class="num">{{ meta?.version }}</span></div>
          <div><span class="muted">构建</span><span class="num">{{ meta?.build }}</span></div>
          <div><span class="muted">TLS 模式</span><span class="num">{{ meta?.tls_mode }}</span></div>
          <div><span class="muted">对外地址</span><span class="mono truncate">{{ meta?.public_base_url || "未配置" }}</span></div>
          <div><span class="muted">服务端运行时长</span><span class="num">{{ auth.server ? Math.floor(auth.server.uptime_seconds / 3600) + " 小时" : "—" }}</span></div>
          <div><span class="muted">统计口径</span><span class="hint">流量为应用层统计，不等于运营商账单</span></div>
        </div>
      </section>

      <Transition name="savebar">
        <div v-if="dirty" class="savebar">
          <span class="dirty-text">有未保存的更改</span>
          <UiButton variant="ghost" :disabled="saving" @click="reset">放弃</UiButton>
          <UiButton variant="primary" :loading="saving" @click="save">保存设置</UiButton>
        </div>
      </Transition>
    </div>
  </AppShell>
</template>

<style scoped>
.loading {
  padding: var(--space-9);
  text-align: center;
}

.settings {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
  max-width: 1000px;
  padding-bottom: 92px;
}

@media (min-width: 2200px) {
  .settings {
    max-width: 1800px;
  }
}

@media (min-width: 3000px) {
  .settings {
    max-width: 2100px;
  }
}

@media (min-width: 3600px) {
  .settings {
    max-width: 2400px;
  }
}

.settings > .panel {
  animation: rise-in 440ms var(--ease-out) both;
}

.settings > .panel:nth-of-type(1) {
  animation-delay: 0ms;
}
.settings > .panel:nth-of-type(2) {
  animation-delay: 55ms;
}
.settings > .panel:nth-of-type(3) {
  animation-delay: 110ms;
}
.settings > .panel:nth-of-type(4) {
  animation-delay: 165ms;
}
.settings > .panel:nth-of-type(5) {
  animation-delay: 220ms;
}

.error-banner {
  padding: 10px 14px;
  border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent);
  border-radius: var(--radius-lg);
  background: var(--danger-soft);
  color: var(--danger);
  font-size: var(--fs-sm);
}

.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
  padding: 20px var(--panel-inset) 22px;
}

.grid :deep(.input) {
  height: 36px;
}

.divider {
  height: 1px;
  margin: 0 var(--panel-inset);
  background: var(--border-subtle);
}

.usage {
  display: flex;
  flex-direction: column;
  gap: 6px;
  justify-content: flex-end;
  padding: 10px 12px;
  border-radius: var(--radius-md);
  background: var(--bg-subtle);
}

.usage-value {
  font-size: var(--fs-sm);
  font-weight: 500;
}

.username-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 18px var(--panel-inset) 20px;
}

.current-name {
  color: var(--text-primary);
  font-weight: 550;
}

.username-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
}
.password-block {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 18px var(--panel-inset) 22px;
}

.block-title {
  font-size: 13.5px;
  font-weight: 550;
}

.password-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr)) auto;
  gap: 8px;
  align-items: center;
}

.segmented {
  display: inline-flex;
  align-self: flex-start;
  gap: 2px;
  padding: 3px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-subtle);
}

.segmented button {
  height: 28px;
  padding: 0 12px;
  border: 0;
  border-radius: var(--radius-xs);
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--fs-xs);
  font-weight: 500;
  cursor: pointer;
  transition: background var(--duration) var(--ease-out), color var(--duration) var(--ease-out);
}

.segmented button:hover {
  color: var(--text-primary);
}

.segmented button.active {
  background: var(--bg-raised);
  color: var(--text-primary);
  box-shadow: var(--shadow-pop);
}

.about {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 24px;
  padding: 10px var(--panel-inset) 16px;
  font-size: var(--fs-sm);
}

.about > div {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  min-width: 0;
  padding: 9px 0;
  border-bottom: 1px solid var(--border-subtle);
}

.about > div > .muted {
  flex: none;
  font-size: var(--fs-xs);
  color: var(--text-tertiary);
}

.about .mono {
  font-size: 11px;
}

.savebar {
  position: fixed;
  left: calc(var(--sidebar-w) + 16px);
  right: 16px;
  bottom: 16px;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  max-width: 1000px;
  margin: 0 auto;
  padding: 10px 12px 10px 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: color-mix(in srgb, var(--bg-raised) 92%, transparent);
  box-shadow: var(--shadow-pop);
  backdrop-filter: blur(12px);
}

.dirty-text {
  margin-right: auto;
  font-size: var(--fs-sm);
  color: var(--text-secondary);
}

.savebar-enter-active,
.savebar-leave-active {
  transition: transform 200ms var(--ease-out), opacity 200ms var(--ease-out);
}

.savebar-enter-from,
.savebar-leave-to {
  transform: translateY(10px);
  opacity: 0;
}

@media (max-width: 1180px) {
  .savebar {
    left: calc(var(--sidebar-w-collapsed) + 16px);
  }
}

@media (max-width: 1023px) {
  .grid,
  .about {
    grid-template-columns: 1fr;
  }
  .password-grid,
  .username-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 767px) {
  .grid {
    padding: 16px;
    gap: 14px;
  }
  .divider {
    margin: 0 16px;
  }
  .username-block {
    padding: 16px;
  }
  .password-block {
    padding: 16px;
  }
  .about {
    padding: 8px 16px 14px;
  }
  .savebar {
    left: 12px;
    right: 12px;
    bottom: 74px;
    padding: 8px 10px 8px 14px;
  }
}
</style>