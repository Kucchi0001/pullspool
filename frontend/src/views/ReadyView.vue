<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

import AppIcon from "@/components/AppIcon.vue";
import AppShell from "@/components/AppShell.vue";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import CopyButton from "@/components/CopyButton.vue";
import EmptyState from "@/components/EmptyState.vue";
import UiButton from "@/components/UiButton.vue";
import { ApiError, api } from "@/services/api";
import { formatBytes, formatDateTime, remaining, shortSha } from "@/services/format";
import type { Task } from "@/services/types";
import { useTasksStore } from "@/stores/tasks";
import { useUiStore } from "@/stores/ui";

const tasks = useTasksStore();
const ui = useUiStore();

const selected = ref<Set<string>>(new Set());
const tick = ref(Date.now());
const ackOpen = ref(false);
const ackTargets = ref<Task[]>([]);
const ackLoading = ref(false);

let timer: number | null = null;

const rows = computed(() => {
  void tick.value;
  return tasks.ready.map((task) => ({ task, expiry: remaining(task.expires_at) }));
});

const allSelected = computed(
  () => rows.value.length > 0 && rows.value.every((row) => selected.value.has(row.task.id)),
);

const selectedTasks = computed(() => tasks.ready.filter((task) => selected.value.has(task.id)));

const selectedBytes = computed(() =>
  selectedTasks.value.reduce((total, task) => total + (task.file_size ?? 0), 0),
);

watch(
  () => tasks.ready.map((task) => task.id).join(","),
  () => {
    const ids = new Set(tasks.ready.map((task) => task.id));
    for (const id of [...selected.value]) {
      if (!ids.has(id)) selected.value.delete(id);
    }
  },
);

function toggle(id: string): void {
  const next = new Set(selected.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  selected.value = next;
}

function toggleAll(): void {
  selected.value = allSelected.value ? new Set() : new Set(tasks.ready.map((task) => task.id));
}

function downloadUrl(id: string): string {
  return api.tasks.downloadUrl(id);
}

function askAck(targets: Task[]): void {
  if (!targets.length) return;
  ackTargets.value = targets;
  ackOpen.value = true;
}

async function confirmAck(): Promise<void> {
  ackLoading.value = true;
  let failures = 0;
  try {
    for (const task of ackTargets.value) {
      try {
        await tasks.acknowledge(task);
      } catch {
        failures += 1;
      }
    }
    if (failures) {
      ui.notify("error", `${failures} 个任务删除失败，请重试`);
    } else {
      ui.notify("success", "已删除服务器上的临时文件");
    }
    ackOpen.value = false;
    selected.value = new Set();
    await tasks.refreshAll();
  } finally {
    ackLoading.value = false;
  }
}

async function copyLink(task: Task): Promise<void> {
  try {
    const url = await tasks.downloadToken(task);
    await navigator.clipboard.writeText(url);
    ui.notify("success", "已复制带令牌的下载链接（30 分钟有效）");
  } catch (caught) {
    ui.notify("error", caught instanceof ApiError ? caught.message : "生成链接失败");
  }
}

onMounted(() => {
  timer = window.setInterval(() => (tick.value = Date.now()), 30_000);
});

onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer);
});
</script>

<template>
  <AppShell title="等待取回">
    <div class="notice reveal" style="--i: 0">
      <span>
        浏览器下载完成并不等于服务器确认你已写入磁盘。请自行确认文件已完整保存后，再点击「确认取回并删除」。
      </span>
    </div>

    <section class="toolbar reveal" style="--i: 1">
      <span class="summary num">
        {{ tasks.ready.length }} 个文件 · {{ formatBytes(tasks.ready.reduce((t, task) => t + (task.file_size ?? 0), 0)) }}
      </span>
      <div class="toolbar-right">
        <UiButton variant="danger" :disabled="!selectedTasks.length" @click="askAck(selectedTasks)">
          确认取回并删除{{ selectedTasks.length ? `（${selectedTasks.length}）` : "" }}
        </UiButton>
      </div>
    </section>

    <section class="panel table-panel reveal" style="--i: 2">
      <div class="table-head">
        <span class="col-check">
          <input
            type="checkbox"
            class="checkbox"
            :checked="allSelected"
            aria-label="全选"
            @change="toggleAll"
          />
        </span>
        <span class="col-name">文件名</span>
        <span class="col-size">大小</span>
        <span class="col-sha">SHA-256</span>
        <span class="col-time">完成时间</span>
        <span class="col-expiry">有效期</span>
        <span class="col-actions">操作</span>
      </div>

      <div v-if="rows.length" class="rows">
        <div v-for="({ task, expiry }, index) in rows" :key="task.id" class="row row-in" :style="`--i:${index}`">
          <span class="col-check">
            <input
              type="checkbox"
              class="checkbox"
              :checked="selected.has(task.id)"
              :aria-label="`选择 ${task.filename}`"
              @change="toggle(task.id)"
            />
          </span>
          <div class="col-name name-cell">
            <div class="name-copy">
              <span class="filename truncate" :title="task.filename">{{ task.filename }}</span>
              <span class="host truncate">{{ task.url_display }}</span>
            </div>
          </div>
          <span class="col-size num">{{ formatBytes(task.file_size) }}</span>
          <span class="col-sha sha">
            <code class="mono truncate" :title="task.sha256 ?? ''">{{ shortSha(task.sha256) }}</code>
            <CopyButton :text="task.sha256" label="复制完整 SHA-256" />
          </span>
          <span class="col-time num muted">{{ formatDateTime(task.completed_at) }}</span>
          <span class="col-expiry num" :class="{ urgent: expiry.urgent }">{{ expiry.text }}</span>
          <div class="col-actions actions">
            <a class="retrieve" :href="downloadUrl(task.id)" download>取回</a>
            <button type="button" class="act" title="复制带令牌链接" @click="copyLink(task)">
              <AppIcon name="link" :size="14" />
            </button>
            <button type="button" class="ack" @click="askAck([task])">确认删除</button>
          </div>
        </div>
      </div>

      <EmptyState
        v-else
        title="没有等待取回的文件"
        description="下载并校验完成后，文件会出现在这里，直到你确认取回或过期清理。"

      />
    </section>

    <div v-if="rows.length" class="mobile-list reveal" style="--i: 2">
      <div v-for="({ task, expiry }, index) in rows" :key="task.id" class="mobile-card panel row-in" :style="`--i:${index}`">
        <div class="mobile-top">
          <input
            type="checkbox"
            class="checkbox"
            :checked="selected.has(task.id)"
            :aria-label="`选择 ${task.filename}`"
            @change="toggle(task.id)"
          />
          <span class="filename truncate">{{ task.filename }}</span>
        </div>
        <div class="mobile-meta num">
          <span>{{ formatBytes(task.file_size) }}</span>
          <span>{{ formatDateTime(task.completed_at) }}</span>
          <span :class="{ urgent: expiry.urgent }">{{ expiry.text }}</span>
        </div>
        <div class="mobile-sha">
          <code class="mono truncate">{{ shortSha(task.sha256) }}</code>
          <CopyButton :text="task.sha256" label="复制 SHA-256" />
        </div>
        <div class="mobile-actions">
          <a class="retrieve" :href="downloadUrl(task.id)" download>取回</a>
          <button type="button" class="act" title="复制带令牌链接" @click="copyLink(task)">
            <AppIcon name="link" :size="14" />
          </button>
          <button type="button" class="ack" @click="askAck([task])">确认删除</button>
        </div>
      </div>
    </div>

    <ConfirmDialog
      :model-value="ackOpen"
      title="确认已保存，并删除服务器文件？"
      :message="`将删除 ${ackTargets.length} 个临时文件（共 ${formatBytes(ackTargets.reduce((t, task) => t + (task.file_size ?? 0), 0))}），删除后不可恢复。请先确认文件已完整保存到本地。`"
      confirm-text="确认删除"
      :loading="ackLoading"
      @update:model-value="ackOpen = false"
      @confirm="confirmAck"
    >
      <ul v-if="ackTargets.length > 1" class="ack-list">
        <li v-for="task in ackTargets" :key="task.id" class="truncate">{{ task.filename }}</li>
      </ul>
      <p v-if="selectedBytes && ackTargets.length" class="hint">这些文件的 SHA-256 会保留在历史记录中。</p>
    </ConfirmDialog>
  </AppShell>
</template>

<style scoped>
.notice {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px var(--panel-inset);
  margin-bottom: var(--space-4);
  border: 1px solid color-mix(in srgb, var(--accent) 18%, var(--border));
  border-radius: var(--radius-lg);
  background: color-mix(in srgb, var(--accent-soft) 55%, var(--bg-surface));
  color: var(--text-secondary);
  font-size: var(--fs-sm);
  line-height: 1.55;
}

.notice :deep(svg) {
  flex: none;
  margin-top: 2px;
  color: var(--accent);
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: 0 var(--panel-inset);
  margin-bottom: var(--space-4);
}

.summary {
  font-size: var(--fs-sm);
  color: var(--text-secondary);
}

.table-panel {
  overflow: clip;
}

.table-head,
.row {
  display: grid;
  grid-template-columns: 26px minmax(220px, 2.2fr) 84px 176px 112px 104px 224px;
  align-items: center;
  gap: var(--space-3);
  padding: 0 var(--panel-inset);
}

@media (min-width: 2200px) {
  .table-head,
  .row {
    grid-template-columns: 32px minmax(260px, 2.8fr) 0.8fr 1.6fr 1fr 1fr 220px;
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
  animation-delay: calc(var(--i, 0) * 40ms + 100ms);
}

.row:hover {
  background: color-mix(in srgb, var(--bg-hover) 65%, transparent);
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
  min-width: 0;
}

.host {
  font-size: 11.5px;
  line-height: 15px;
  color: var(--text-tertiary);
  min-width: 0;
}

.col-size,
.col-time {
  text-align: right;
  font-size: var(--fs-sm);
  color: var(--text-secondary);
}

.col-size {
  color: var(--text-primary);
  font-weight: 500;
}

.sha {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}

.sha code {
  min-width: 0;
  padding: 2px 6px;
  border-radius: var(--radius-xs);
  background: var(--bg-subtle);
  color: var(--text-tertiary);
  font-size: 10.5px;
}

.col-expiry {
  font-size: 11px;
  color: var(--text-secondary);
}

.col-expiry.urgent,
.urgent {
  color: var(--warning);
}

.actions {
  display: flex;
  align-items: center;
  gap: 4px;
  justify-content: flex-end;
  opacity: 0.82;
  transition: opacity var(--duration) var(--ease-out);
}

.row:hover .actions {
  opacity: 1;
}

.retrieve {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 12px;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: var(--accent-contrast);
  font-size: var(--fs-xs);
  font-weight: 550;
  white-space: nowrap;
  transition: background var(--duration) var(--ease-out);
}

.retrieve:hover {
  background: var(--accent-hover);
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
}

.act:hover {
  background: var(--bg-active);
  color: var(--text-primary);
}

.ack {
  height: 30px;
  padding: 0 9px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-tertiary);
  font-size: 11.5px;
  cursor: pointer;
  white-space: nowrap;
  transition: background var(--duration) var(--ease-out), color var(--duration) var(--ease-out);
}

.ack:hover {
  background: var(--danger-soft);
  color: var(--danger);
}

.ack-list {
  margin: var(--space-3) 0 0;
  padding-left: 18px;
  max-height: 140px;
  overflow-y: auto;
  color: var(--text-secondary);
  font-size: var(--fs-sm);
}

.mobile-card.row-in {
  animation-delay: calc(var(--i, 0) * 40ms + 80ms);
}

.mobile-list {
  display: none;
}

@media (max-width: 1279px) {
  .table-head,
  .row {
    grid-template-columns: 26px minmax(200px, 2fr) 80px 160px 92px 212px;
  }
  .col-time {
    display: none;
  }
}

@media (max-width: 1023px) {
  .table-head,
  .row {
    grid-template-columns: 26px minmax(180px, 2fr) 76px 132px 200px;
  }
  .col-sha {
    display: none;
  }
}

@media (max-width: 767px) {
  .notice {
    padding: 12px 14px;
  }
  .toolbar {
    padding: 0 2px;
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
    min-width: 0;
  }
  .mobile-top .filename {
    flex: 1;
    font-size: 14px;
  }
  .mobile-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    color: var(--text-tertiary);
    font-size: 11px;
  }
  .mobile-sha {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .mobile-sha code {
    padding: 2px 6px;
    border-radius: var(--radius-xs);
    background: var(--bg-subtle);
    font-size: 10.5px;
    color: var(--text-tertiary);
  }
  .mobile-actions {
    display: flex;
    align-items: center;
    gap: 6px;
    padding-top: 2px;
  }
  .mobile-actions .ack {
    margin-left: auto;
  }
}
</style>