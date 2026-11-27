<script setup lang="ts">
import { computed, ref } from "vue";

import AppIcon from "@/components/AppIcon.vue";
import AppShell from "@/components/AppShell.vue";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import EmptyState from "@/components/EmptyState.vue";
import FilterChips from "@/components/FilterChips.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import UiButton from "@/components/UiButton.vue";
import { ApiError } from "@/services/api";
import {
  formatBytes,
  formatDateTime,
  formatDuration,
  formatPercent,
  formatSpeed,
} from "@/services/format";
import type { Task } from "@/services/types";
import { useTasksStore } from "@/stores/tasks";
import { useUiStore } from "@/stores/ui";

const tasks = useTasksStore();
const ui = useUiStore();

const filter = ref("all");
const search = ref("");
const busyId = ref<string | null>(null);

const cancelTarget = ref<Task | null>(null);
const cancelDeleteFiles = ref(true);
const cancelLoading = ref(false);

const deleteTarget = ref<Task | null>(null);
const deleteLoading = ref(false);

const chips = computed(() => [
  { value: "all", label: "全部", count: tasks.downloads.length },
  { value: "downloading", label: "下载中", count: tasks.counts.downloading + tasks.counts.verifying },
  { value: "queued", label: "等待中", count: tasks.counts.queued },
  { value: "paused", label: "已暂停", count: tasks.counts.paused },
  { value: "failed", label: "失败", count: tasks.counts.failed },
  { value: "canceled", label: "已取消", count: tasks.counts.canceled },
]);

const filtered = computed(() => {
  const needle = search.value.trim().toLowerCase();
  return tasks.downloads.filter((task) => {
    if (filter.value === "downloading") {
      if (task.ui_status !== "downloading" && task.ui_status !== "verifying") return false;
    } else if (filter.value !== "all" && task.status !== filter.value) {
      return false;
    }
    if (needle) {
      return (
        task.filename.toLowerCase().includes(needle) ||
        task.url_display.toLowerCase().includes(needle)
      );
    }
    return true;
  });
});

function errorText(task: Task): string {
  const message = task.error_message ?? "";
  if (task.error_code === "ARIA2_ERROR") {
    if (/no uri available/i.test(message)) return "下载链接已失效，或源站中断了传输";
    if (/failed to make the directory/i.test(message)) return "无法创建任务目录，请检查数据目录权限";
    if (/timeout|timed out/i.test(message)) return "连接目标站点超时，请稍后重试";
    return "下载引擎出错，建议重试；若反复失败请检查源站";
  }
  return message || "下载失败";
}
function hostOf(task: Task): string {
  try {
    return new URL(task.url_display).host;
  } catch {
    return task.url_display;
  }
}

function canPause(task: Task): boolean {
  return task.status === "active" || task.status === "queued";
}

function canResume(task: Task): boolean {
  return task.status === "paused";
}

function canCancel(task: Task): boolean {
  return ["active", "queued", "paused"].includes(task.status);
}

async function run(task: Task, action: () => Promise<void>): Promise<void> {
  busyId.value = task.id;
  try {
    await action();
  } catch (caught) {
    ui.notify("error", caught instanceof ApiError ? caught.message : "操作失败");
  } finally {
    busyId.value = null;
  }
}

function askCancel(task: Task): void {
  cancelTarget.value = task;
  cancelDeleteFiles.value = true;
}

async function confirmCancel(): Promise<void> {
  const task = cancelTarget.value;
  if (!task) return;
  cancelLoading.value = true;
  try {
    await tasks.cancel(task, cancelDeleteFiles.value);
    ui.notify("success", "任务已取消");
    cancelTarget.value = null;
  } catch (caught) {
    ui.notify("error", caught instanceof ApiError ? caught.message : "取消失败");
  } finally {
    cancelLoading.value = false;
  }
}

function askDelete(task: Task): void {
  deleteTarget.value = task;
}

async function confirmDelete(): Promise<void> {
  const task = deleteTarget.value;
  if (!task) return;
  deleteLoading.value = true;
  try {
    await tasks.remove(task, true);
    ui.notify("success", "记录已删除");
    deleteTarget.value = null;
  } catch (caught) {
    ui.notify("error", caught instanceof ApiError ? caught.message : "删除失败");
  } finally {
    deleteLoading.value = false;
  }
}
</script>

<template>
  <AppShell title="下载">
    <section class="toolbar reveal" style="--i: 0">
      <div class="search">
        <AppIcon name="search" :size="14" class="search-icon" />
        <input
          v-model="search"
          class="input search-input"
          type="search"
          placeholder="搜索文件名或链接"
          aria-label="搜索任务"
        />
      </div>
      <FilterChips v-model="filter" :options="chips" />
      <div class="toolbar-right">
        <UiButton variant="primary" class="toolbar-new" @click="ui.openNewTask()">
          新建下载
        </UiButton>
      </div>
    </section>

    <section class="panel table-panel reveal" style="--i: 1">
      <div class="table-head">
        <span class="col-name">文件名</span>
        <span class="col-size">大小</span>
        <span class="col-status">状态</span>
        <span class="col-progress">进度</span>
        <span class="col-speed">速度</span>
        <span class="col-eta">剩余</span>
        <span class="col-time">创建时间</span>
        <span class="col-actions">操作</span>
      </div>

      <div v-if="filtered.length" class="rows">
        <div v-for="(task, index) in filtered" :key="task.id" class="row row-in" :style="`--i:${index}`">
          <div class="col-name name-cell">
            <div class="name-copy">
              <span class="filename truncate" :title="task.filename">{{ task.filename }}</span>
              <span v-if="task.error_message" class="error-line truncate" :title="task.error_message">
                {{ errorText(task) }}
              </span>
              <span v-else class="host truncate">{{ hostOf(task) }}</span>
            </div>
          </div>
          <span class="col-size num">{{ formatBytes(task.file_size) }}</span>
          <span class="col-status"><StatusBadge :status="task.ui_status" /></span>
          <div class="col-progress progress-cell">
            <ProgressBar :value="task.progress" :status="task.status" />
            <span class="num percent">{{ formatPercent(task.progress) }}</span>
          </div>
          <span class="col-speed num">{{ formatSpeed(task.download_speed) }}</span>
          <span class="col-eta num">{{ formatDuration(task.eta_seconds) }}</span>
          <span class="col-time num muted">{{ formatDateTime(task.created_at) }}</span>
          <div class="col-actions actions">
            <button
              v-if="canPause(task)"
              type="button"
              class="act"
              title="暂停"
              :disabled="busyId === task.id"
              @click="run(task, () => tasks.pause(task))"
            >
              <AppIcon name="pause" :size="14" />
            </button>
            <button
              v-if="canResume(task)"
              type="button"
              class="act"
              title="恢复"
              :disabled="busyId === task.id"
              @click="run(task, () => tasks.resume(task))"
            >
              <AppIcon name="play" :size="14" />
            </button>
            <button
              v-if="task.status === 'failed'"
              type="button"
              class="act"
              title="重试"
              :disabled="busyId === task.id"
              @click="run(task, () => tasks.retry(task))"
            >
              <AppIcon name="refresh" :size="14" />
            </button>
            <button
              v-if="canCancel(task)"
              type="button"
              class="act"
              title="取消任务"
              :disabled="busyId === task.id"
              @click="askCancel(task)"
            >
              <AppIcon name="x" :size="14" />
            </button>
            <button
              v-if="task.status === 'failed' || task.status === 'canceled'"
              type="button"
              class="act danger"
              title="删除记录"
              :disabled="busyId === task.id"
              @click="askDelete(task)"
            >
              <AppIcon name="trash" :size="14" />
            </button>
          </div>
        </div>
      </div>

      <EmptyState
        v-else
        :title="search ? '没有匹配的任务' : '还没有下载任务'"
        :description="search ? '换个关键词试试。' : '粘贴一个下载链接，VPS 会用自身网络下载并暂存。'"

      >
        <UiButton v-if="!search" variant="primary" @click="ui.openNewTask()">新建下载</UiButton>
      </EmptyState>

      <footer v-if="filtered.length" class="table-foot">
        <span class="num">共 {{ filtered.length }} 个任务</span>
        <span class="num">
          {{ tasks.counts.downloading }} 个下载中 · {{ tasks.counts.ready }} 个等待取回
        </span>
      </footer>
    </section>

    <div v-if="filtered.length" class="mobile-list reveal" style="--i: 1">
      <div v-for="(task, index) in filtered" :key="task.id" class="mobile-card panel row-in" :style="`--i:${index}`">
        <div class="mobile-top">
          <span class="filename truncate">{{ task.filename }}</span>
          <StatusBadge :status="task.ui_status" />
        </div>
        <span v-if="task.error_message" class="error-line truncate" :title="task.error_message">{{ errorText(task) }}</span>
        <span v-else class="host truncate">{{ hostOf(task) }}</span>
        <div class="mobile-progress">
          <ProgressBar :value="task.progress" :status="task.status" />
          <span class="num percent">{{ formatPercent(task.progress) }}</span>
        </div>
        <div class="mobile-meta num">
          <span>{{ formatBytes(task.file_size) }}</span>
          <span>{{ formatSpeed(task.download_speed) }}</span>
          <span>{{ formatDateTime(task.created_at) }}</span>
        </div>
        <div class="mobile-actions">
          <UiButton v-if="canPause(task)" size="sm" @click="run(task, () => tasks.pause(task))">暂停</UiButton>
          <UiButton v-if="canResume(task)" size="sm" @click="run(task, () => tasks.resume(task))">恢复</UiButton>
          <UiButton v-if="task.status === 'failed'" size="sm" @click="run(task, () => tasks.retry(task))">重试</UiButton>
          <UiButton v-if="canCancel(task)" size="sm" variant="danger" @click="askCancel(task)">取消</UiButton>
          <UiButton
            v-if="task.status === 'failed' || task.status === 'canceled'"
            size="sm"
            variant="danger"
            @click="askDelete(task)"
          >
            删除记录
          </UiButton>
        </div>
      </div>
    </div>

    <ConfirmDialog
      :model-value="cancelTarget !== null"
      title="取消这个下载任务？"
      :message="cancelTarget ? `任务「${cancelTarget.filename}」将停止下载。` : ''"
      confirm-text="取消任务"
      :loading="cancelLoading"
      @update:model-value="cancelTarget = null"
      @confirm="confirmCancel"
    >
      <label class="check-row">
        <input v-model="cancelDeleteFiles" type="checkbox" class="checkbox" />
        同时删除已下载的临时文件
      </label>
    </ConfirmDialog>

    <ConfirmDialog
      :model-value="deleteTarget !== null"
      title="删除任务记录？"
      :message="deleteTarget ? `任务「${deleteTarget.filename}」的记录和残留文件将被删除。` : ''"
      confirm-text="删除"
      :loading="deleteLoading"
      @update:model-value="deleteTarget = null"
      @confirm="confirmDelete"
    />
  </AppShell>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
  padding: 10px var(--panel-inset);
  margin-bottom: var(--space-4);
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-soft);
}

.search {
  position: relative;
  flex: 1 1 240px;
  max-width: 320px;
}

.search-icon {
  position: absolute;
  left: 11px;
  top: 10px;
  color: var(--text-tertiary);
  pointer-events: none;
}

.search-input {
  height: 36px;
  padding-left: 34px;
  background: var(--bg-subtle);
  border-color: transparent;
  border-radius: var(--radius-md);
}

.search-input:focus {
  background: var(--bg-raised);
  border-color: var(--accent);
}

.toolbar-right {
  margin-left: auto;
}

@media (min-width: 1181px) {
  .toolbar-new {
    display: none;
  }
}

.table-panel {
  overflow: clip;
}

.table-head,
.row {
  display: grid;
  grid-template-columns: minmax(220px, 2.4fr) 84px 104px 176px 88px 72px 108px 116px;
  align-items: center;
  gap: var(--space-3);
  padding: 0 var(--panel-inset);
}

@media (min-width: 2200px) {
  .table-head,
  .row {
    grid-template-columns: minmax(240px, 2.2fr) 0.65fr 0.85fr 1.4fr 0.65fr 0.55fr 0.85fr 0.85fr;
  }
}

.table-head {
  position: sticky;
  top: var(--topbar-h);
  z-index: 10;
  height: var(--table-head-h);
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-subtle);
  font-size: var(--table-head-fs);
  font-weight: 500;
  letter-spacing: 0.02em;
  color: var(--text-tertiary);
}

.table-head .col-size,
.table-head .col-speed,
.table-head .col-eta,
.table-head .col-time,
.table-head .col-actions {
  text-align: right;
}

.rows {
  display: flex;
  flex-direction: column;
}

.row {
  min-height: var(--row-h);
  padding-top: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-subtle);
  transition: background var(--duration) var(--ease-out);
}

.row:last-child {
  border-bottom: 0;
}

.row.row-in {
  animation-delay: calc(var(--i, 0) * 40ms + 80ms);
}

.row:hover {
  background: color-mix(in srgb, var(--bg-hover) 70%, transparent);
}

.name-cell {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.name-copy {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.filename {
  font-size: 13.5px;
  font-weight: 500;
  letter-spacing: -0.01em;
  min-width: 0;
}

.host,
.error-line {
  font-size: 11.5px;
  line-height: 15px;
  color: var(--text-tertiary);
  min-width: 0;
}

.error-line {
  color: var(--danger);
}

.col-size,
.col-time,
.col-speed,
.col-eta {
  text-align: right;
  font-size: var(--fs-sm);
  color: var(--text-secondary);
}

.col-size {
  color: var(--text-primary);
  font-weight: 500;
}

.col-status {
  display: flex;
}

.progress-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.percent {
  width: 36px;
  flex: none;
  text-align: right;
  font-size: 11px;
  color: var(--text-tertiary);
}

.actions {
  display: flex;
  align-items: center;
  gap: 2px;
  justify-content: flex-end;
  opacity: 0.72;
  transition: opacity var(--duration) var(--ease-out);
}

.row:hover .actions {
  opacity: 1;
}

.act {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: background var(--duration) var(--ease-out), color var(--duration) var(--ease-out);
}

.act:hover:not(:disabled) {
  background: var(--bg-active);
  color: var(--text-primary);
}

.act.danger:hover:not(:disabled) {
  background: var(--danger-soft);
  color: var(--danger);
}

.act:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.check-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: var(--space-5);
  font-size: var(--fs-sm);
  color: var(--text-secondary);
}

.table-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  height: 42px;
  padding: 0 var(--panel-inset);
  border-top: 1px solid var(--border-subtle);
  color: var(--text-tertiary);
  font-size: 11px;
}

.mobile-card.row-in {
  animation-delay: calc(var(--i, 0) * 40ms + 60ms);
}

.mobile-list {
  display: none;
}

:global([data-density="compact"]) .row {
  min-height: var(--row-h-compact);
}

@media (max-width: 1279px) {
  .table-head,
  .row {
    grid-template-columns: minmax(200px, 2fr) 82px 100px 160px 84px 88px;
  }
  .col-eta,
  .col-time {
    display: none;
  }
}

@media (max-width: 1023px) {
  .table-head,
  .row {
    grid-template-columns: minmax(180px, 2fr) 80px 100px 150px 80px;
  }
  .col-speed {
    display: none;
  }
}

@media (max-width: 767px) {
  .toolbar {
    padding: 10px 12px;
    gap: 8px;
  }
  .search {
    flex-basis: 100%;
    max-width: none;
  }
  .table-panel {
    display: none;
  }
  .mobile-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .mobile-card {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 14px;
    border-radius: var(--radius-lg);
    background: var(--bg-surface);
  }
  .mobile-top {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .mobile-top .filename {
    flex: 1;
    font-size: 14px;
  }
  .mobile-progress {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .mobile-meta {
    display: flex;
    gap: 12px;
    color: var(--text-tertiary);
    font-size: 11px;
  }
  .mobile-actions {
    display: flex;
    gap: 6px;
    padding-top: 2px;
  }
}
</style>