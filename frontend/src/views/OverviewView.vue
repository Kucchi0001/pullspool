<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useRouter } from "vue-router";

import AppShell from "@/components/AppShell.vue";
import EmptyState from "@/components/EmptyState.vue";
import KpiCard from "@/components/KpiCard.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import TrafficChart from "@/components/TrafficChart.vue";
import UiButton from "@/components/UiButton.vue";
import { api } from "@/services/api";
import {
  formatBytes,
  formatDateTime,
  formatDuration,
  formatPercent,
  formatSpeed,
  formatTraffic,
} from "@/services/format";
import type { Task } from "@/services/types";
import { useSystemStore } from "@/stores/system";
import { useTasksStore } from "@/stores/tasks";

const tasks = useTasksStore();
const system = useSystemStore();
const router = useRouter();

const activeTop = computed(() => tasks.active.slice(0, 6));
const readyTop = computed(() => tasks.ready.slice(0, 5));

const currentSpeed = computed(() =>
  tasks.active.reduce((total, task) => total + task.download_speed, 0),
);

const readyBytes = computed(() =>
  tasks.ready.reduce((total, task) => total + (task.file_size ?? 0), 0),
);

const storageBytes = computed(() => system.storage?.downloads_bytes ?? 0);
const storageQuota = computed(
  () => system.status?.storage.quota_bytes ?? system.storage?.quota_bytes ?? 0,
);
const storageRatio = computed(() =>
  storageQuota.value > 0 ? Math.min(1, storageBytes.value / storageQuota.value) : null,
);

const todayDown = computed(() => system.traffic?.totals.today_download_bytes ?? 0);
const todayUp = computed(() => system.traffic?.totals.today_upload_bytes ?? 0);
const monthDown = computed(() => system.traffic?.totals.month_download_bytes ?? 0);

const host = computed(() => system.status?.host ?? null);
const aria2 = computed(() => system.status?.aria2 ?? null);
const queue = computed(() => system.status?.queue ?? null);

const diskRatio = computed(() => {
  if (!host.value || host.value.disk_total <= 0) return null;
  return host.value.disk_used / host.value.disk_total;
});

const guardLabel = computed(() => {
  const guarded = aria2.value?.guarded;
  if (guarded === "ok") return "已启用";
  if (guarded === "failed") return "安装失败";
  if (guarded === "disabled") return "已关闭";
  return "未知";
});

const guardTone = computed(() => {
  const guarded = aria2.value?.guarded;
  if (guarded === "ok") return "ok";
  if (guarded === "failed") return "bad";
  return "muted";
});

function downloadUrl(id: string): string {
  return api.tasks.downloadUrl(id);
}

function openDownloads(): void {
  void router.push({ name: "downloads" });
}

function openReady(): void {
  void router.push({ name: "ready" });
}

function sizeLabel(task: Task): string {
  return formatBytes(task.file_size);
}

function progressPair(task: Task): string {
  if (!task.file_size) return "—";
  return `${formatBytes(task.downloaded_size)} / ${formatBytes(task.file_size)}`;
}

function etaLabel(task: Task): string {
  const label = formatDuration(task.eta_seconds);
  return label === "—" ? "剩余时间未知" : `剩余 ${label}`;
}

onMounted(() => {
  void system.refreshStorage();
  void system.refreshTraffic(14);
});
</script>

<template>
  <AppShell title="总览">
    <section class="stat-rail panel reveal" style="--i: 0">
      <KpiCard
        label="下载中"
        :value="String(tasks.counts.downloading)"
        :sub="currentSpeed > 0 ? formatSpeed(currentSpeed) : '当前无活动任务'"
      />
      <KpiCard
        label="等待取回"
        :value="String(tasks.counts.ready)"
        :sub="readyBytes > 0 ? formatBytes(readyBytes) : '暂无待取回文件'"
      />
      <KpiCard
        label="临时存储"
        :value="formatBytes(storageBytes)"
        :sub="`配额 ${formatBytes(storageQuota)}`"
      >
        <div class="rail-progress">
          <ProgressBar :value="storageRatio" status="ready" :height="4" />
        </div>
      </KpiCard>
      <KpiCard
        label="今日流量"
        :value="formatTraffic(todayDown)"
        :sub="`回传 ${formatTraffic(todayUp)} · 本月 ${formatTraffic(monthDown)}`"
      />
    </section>

    <div class="overview-grid">
      <div class="main-column">
        <section class="panel tasks-panel reveal" style="--i: 1">
          <header class="panel-header">
            <div class="header-title">
              <span class="section-title">正在下载</span>
              <span class="count-pill num">{{ activeTop.length }}</span>
            </div>
            <button type="button" class="link" @click="openDownloads">
              查看全部
            </button>
          </header>

          <div v-if="activeTop.length" class="task-list">
            <div v-for="(task, index) in activeTop" :key="task.id" class="task-row row-in" :style="`--i:${index}`">
              <div class="task-info">
                <span class="task-name truncate" :title="task.filename">{{ task.filename }}</span>
                <div class="task-sub">
                  <StatusBadge :status="task.ui_status" />
                  <span v-if="task.download_speed > 0" class="dot-sep num">
                    {{ formatSpeed(task.download_speed) }}
                  </span>
                  <span class="dot-sep num">{{ etaLabel(task) }}</span>
                </div>
              </div>
              <div class="task-progress">
                <div class="progress-meta num">
                  <span class="progress-pair">{{ progressPair(task) }}</span>
                  <span class="progress-percent">{{ formatPercent(task.progress) }}</span>
                </div>
                <ProgressBar :value="task.progress" :status="task.status" :height="5" />
              </div>
            </div>
          </div>

          <EmptyState
            v-else
            title="当前没有进行中的下载"
            description="在「下载」页面粘贴链接，VPS 会下载并暂存文件。"
          >
            <UiButton variant="primary" @click="openDownloads">
              新建下载
            </UiButton>
          </EmptyState>
        </section>

        <section class="panel ready-panel reveal" style="--i: 2">
          <header class="panel-header">
            <div class="header-title">
              <span class="section-title">最近可取回</span>
              <span v-if="readyTop.length" class="count-pill num">{{ tasks.counts.ready }}</span>
            </div>
            <button type="button" class="link" @click="openReady">
              查看全部
            </button>
          </header>

          <div v-if="readyTop.length" class="ready-list">
            <div v-for="(task, index) in readyTop" :key="task.id" class="ready-row row-in" :style="`--i:${index}`">
              <div class="ready-info">
                <span class="task-name truncate" :title="task.filename">{{ task.filename }}</span>
                <span class="ready-meta num">
                  {{ sizeLabel(task) }}
                  <span class="meta-dot">·</span>
                  {{ formatDateTime(task.completed_at) }}
                </span>
              </div>
              <a class="retrieve" :href="downloadUrl(task.id)" download>
                取回
              </a>
            </div>
          </div>

          <EmptyState
            v-else
            title="还没有等待取回的文件"
            description="下载完成后会出现在这里，确认保存后再删除服务器上的副本。"
          />
        </section>
      </div>

      <aside class="side-column">
        <section class="panel engine-panel reveal" style="--i: 3">
          <header class="panel-header">
            <span class="section-title">引擎与存储</span>
            <span v-if="system.status?.public_ip" class="ip-chip num" :title="system.status.public_ip">
              IP {{ system.status.public_ip }}
            </span>
            <span v-else class="ip-chip muted">IP 未配置</span>
          </header>

          <div class="engine-body">
            <div class="engine-hero">
              <span class="engine-label">下载引擎</span>
              <span class="engine-value" :class="aria2?.reachable ? 'ok' : 'bad'">
                <span class="status-dot" />
                {{ aria2?.reachable ? "运行中" : "不可用" }}
              </span>
            </div>

            <div class="chip-grid">
              <div class="mini-chip">
                <span class="mini-chip-label">出站防火墙</span>
                <strong :class="guardTone">{{ guardLabel }}</strong>
              </div>
              <div class="mini-chip">
                <span class="mini-chip-label">下载队列</span>
                <strong class="num">
                  {{ queue ? `${queue.active} / ${queue.max_concurrent}` : "—" }}
                </strong>
              </div>
            </div>
            <p v-if="queue?.paused_reason === 'disk_low'" class="warn-line">
              磁盘不足，队列已暂停
            </p>

            <div class="storage-block">
              <div class="storage-head">
                <span class="storage-label">临时存储</span>
                <span class="storage-value num">
                  {{ formatBytes(storageBytes) }}
                  <em>/ {{ formatBytes(storageQuota) }}</em>
                </span>
              </div>
              <ProgressBar :value="storageRatio" status="ready" :height="5" />
            </div>

            <div class="engine-metrics">
              <div class="metric-chip" :title="host ? `CPU ${host.cpu_percent.toFixed(0)}%` : 'CPU'">
                <span>CPU</span>
                <strong class="num">{{ host ? `${host.cpu_percent.toFixed(0)}%` : "—" }}</strong>
              </div>
              <div
                class="metric-chip"
                :title="host ? `内存 ${formatBytes(host.mem_used)} / ${formatBytes(host.mem_total)}` : '内存'"
              >
                <span>内存</span>
                <strong class="num">{{ host ? `${host.mem_percent.toFixed(0)}%` : "—" }}</strong>
              </div>
              <div
                class="metric-chip"
                :title="host ? `磁盘 ${formatBytes(host.disk_used)} / ${formatBytes(host.disk_total)}` : '磁盘'"
              >
                <span>磁盘</span>
                <strong class="num">{{ diskRatio !== null ? `${(diskRatio * 100).toFixed(0)}%` : "—" }}</strong>
              </div>
            </div>

            <div class="engine-foot">
              <span class="num">回传 {{ queue?.transferring ?? 0 }}</span>
              <span class="num">
                运行 {{ system.status ? `${Math.floor(system.status.server.uptime_seconds / 3600)} 小时` : "—" }}
              </span>
            </div>
          </div>
        </section>

      </aside>

      <section class="panel traffic-panel reveal" style="--i: 4">
        <header class="panel-header">
          <span class="section-title">近 14 天流量</span>
          <span class="muted small">应用层统计</span>
        </header>
        <div class="traffic-body">
          <div class="chart-area">
            <TrafficChart :days="system.traffic?.days ?? []" />
          </div>
          <div class="totals-area">
            <div class="totals">
              <div class="total-row">
                <span class="total-label">今日下载</span>
                <strong class="num">{{ formatTraffic(todayDown) }}</strong>
              </div>
              <div class="total-row">
                <span class="total-label">今日回传</span>
                <strong class="num">{{ formatTraffic(todayUp) }}</strong>
              </div>
              <div class="total-row">
                <span class="total-label">本月下载</span>
                <strong class="num">{{ formatTraffic(monthDown) }}</strong>
              </div>
            </div>
            <p class="hint">{{ system.traffic?.note }}</p>
          </div>
        </div>
      </section>
    </div>
  </AppShell>
</template>

<style scoped>
.stat-rail {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-bottom: var(--space-6);
  overflow: hidden;
}

.stat-rail > :deep(.kpi) + :deep(.kpi) {
  border-left: 1px solid var(--border-subtle);
}

.rail-progress {
  margin-top: 8px;
  max-width: 160px;
}

.overview-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.9fr) minmax(0, 1fr);
  gap: var(--space-6);
  align-items: start;
}

.main-column,
.side-column {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
  min-width: 0;
}

.header-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.count-pill {
  min-width: 20px;
  height: 20px;
  padding: 0 7px;
  border-radius: var(--radius-pill);
  background: var(--bg-subtle);
  color: var(--text-secondary);
  font-size: 10.5px;
  line-height: 20px;
  text-align: center;
}

.link {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  border: 0;
  background: transparent;
  color: var(--text-tertiary);
  font-size: var(--fs-xs);
  cursor: pointer;
  padding: 4px 2px;
  border-radius: var(--radius-xs);
  transition: color var(--duration) var(--ease-out);
}

.link:hover {
  color: var(--accent);
}

/* ------------------------------------------------------------- task list */
.task-list {
  display: flex;
  flex-direction: column;
}

.task-row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px var(--panel-inset);
  border-bottom: 1px solid var(--border-subtle);
  transition: background var(--duration) var(--ease-out);
}

.task-row:last-child {
  border-bottom: 0;
}

.task-row.row-in {
  animation-delay: calc(var(--i, 0) * 45ms + 80ms);
}

.task-row:hover {
  background: color-mix(in srgb, var(--bg-hover) 60%, transparent);
}

.task-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.task-name {
  font-size: 14px;
  font-weight: 500;
  letter-spacing: -0.012em;
}

.task-sub {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.dot-sep {
  font-size: 11px;
  color: var(--text-tertiary);
}

.task-progress {
  flex: none;
  width: 230px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.progress-meta {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  font-size: 11px;
  color: var(--text-tertiary);
}

.progress-pair {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.progress-percent {
  flex: none;
  color: var(--text-secondary);
  font-weight: 500;
}

/* -------------------------------------------------------------- ready list */
.ready-list {
  display: flex;
  flex-direction: column;
}

.ready-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px var(--panel-inset);
  border-bottom: 1px solid var(--border-subtle);
  transition: background var(--duration) var(--ease-out);
}

.ready-row:last-child {
  border-bottom: 0;
}

.ready-row.row-in {
  animation-delay: calc(var(--i, 0) * 45ms + 120ms);
}

.ready-row:hover {
  background: color-mix(in srgb, var(--bg-hover) 60%, transparent);
}

.ready-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.ready-meta {
  font-size: 11.5px;
  color: var(--text-tertiary);
}

.meta-dot {
  margin: 0 3px;
}

.retrieve {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: none;
  height: 30px;
  padding: 0 11px;
  border-radius: var(--radius-sm);
  background: var(--accent-soft);
  color: var(--accent);
  font-size: var(--fs-xs);
  font-weight: 550;
  transition: background var(--duration) var(--ease-out), color var(--duration) var(--ease-out);
}

.retrieve:hover {
  background: var(--accent);
  color: var(--accent-contrast);
}

/* ------------------------------------------------------------------ engine */
.ip-chip {
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 3px 8px;
  border-radius: var(--radius-pill);
  background: var(--bg-subtle);
  color: var(--text-tertiary);
  font-size: 10.5px;
}

.engine-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 18px var(--panel-inset) 20px;
}

.engine-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.engine-label {
  font-size: 11px;
  letter-spacing: 0.02em;
  color: var(--text-tertiary);
}

.engine-value {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.ok {
  color: var(--success);
}

.bad {
  color: var(--danger);
}

.muted {
  color: var(--text-tertiary);
}

.chip-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.mini-chip {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 9px 11px;
  border-radius: var(--radius-md);
  background: var(--bg-subtle);
}

.mini-chip-label {
  font-size: 10.5px;
  color: var(--text-tertiary);
}

.mini-chip strong {
  font-size: 12.5px;
  font-weight: 550;
  color: var(--text-primary);
}

.mini-chip strong.ok {
  color: var(--success);
}

.mini-chip strong.bad {
  color: var(--danger);
}

.warn-line {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: -6px;
  font-size: 11px;
  color: var(--warning);
}

.storage-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 4px;
}

.storage-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.storage-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.storage-value {
  font-size: 12.5px;
  font-weight: 550;
}

.storage-value em {
  font-style: normal;
  font-weight: 400;
  color: var(--text-tertiary);
}

.engine-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.metric-chip {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding: 9px 10px;
  border-radius: var(--radius-md);
  background: var(--bg-subtle);
}

.metric-chip span {
  font-size: 10.5px;
  color: var(--text-tertiary);
}

.metric-chip strong {
  font-size: 13px;
  font-weight: 550;
  color: var(--text-primary);
}
.engine-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border-subtle);
  font-size: 11px;
  color: var(--text-tertiary);
}

/* ----------------------------------------------------------------- traffic */
.traffic-panel {
  grid-column: 1 / -1;
}

.traffic-body {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(260px, 1fr);
  gap: 28px;
  padding: 18px var(--panel-inset) 20px;
  align-items: start;
}

.chart-area {
  min-width: 0;
}

.totals-area {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-left: 24px;
  border-left: 1px solid var(--border-subtle);
}

.small {
  font-size: var(--fs-xs);
}

.totals {
  display: flex;
  flex-direction: column;
}

.total-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 0;
  border-bottom: 1px solid var(--border-subtle);
}

.total-row:first-child {
  padding-top: 2px;
}

.total-row:last-child {
  border-bottom: 0;
}

.total-label {
  font-size: 11px;
  color: var(--text-tertiary);
  white-space: nowrap;
}

.totals strong {
  font-size: 14px;
  font-weight: 550;
  letter-spacing: -0.01em;
  white-space: nowrap;
}

/* ------------------------------------------------------------- responsive */
@media (max-width: 1279px) {
  .overview-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 1023px) {
  .stat-rail {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .stat-rail > :deep(.kpi):nth-child(3) {
    border-left: 0;
    border-top: 1px solid var(--border-subtle);
  }
  .stat-rail > :deep(.kpi):nth-child(4) {
    border-top: 1px solid var(--border-subtle);
  }
}

@media (max-width: 767px) {
  .stat-rail {
    margin-bottom: var(--space-6);
  }
  .stat-rail :deep(.kpi) {
    padding: 16px;
    gap: 2px;
  }
  .stat-rail :deep(.value) {
    font-size: 22px;
    line-height: 26px;
  }
  .stat-rail :deep(.sub) {
    white-space: normal;
    line-height: 15px;
  }
  .task-row {
    align-items: flex-start;
    gap: 10px;
    padding: 14px 16px;
  }
  .task-progress {
    width: 100%;
    margin-top: 2px;
  }
  .task-row {
    flex-wrap: wrap;
  }
  .task-info {
    flex-basis: 100%;
  }
  .ready-row {
    padding: 12px 16px;
  }
  .engine-body {
    padding: 14px 16px 18px;
  }
  .traffic-body {
    grid-template-columns: 1fr;
    gap: 18px;
    padding: 14px 16px 18px;
  }
  .totals-area {
    padding-left: 0;
    border-left: 0;
    padding-top: 14px;
    border-top: 1px solid var(--border-subtle);
  }
  .metrics {
    grid-template-columns: 1fr;
  }
}
</style>
