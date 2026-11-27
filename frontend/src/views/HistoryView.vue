<script setup lang="ts">
import { computed, ref } from "vue";

import AppShell from "@/components/AppShell.vue";
import EmptyState from "@/components/EmptyState.vue";
import FilterChips from "@/components/FilterChips.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import { formatBytes, formatDateTime, formatTraffic, shortSha } from "@/services/format";
import type { Task } from "@/services/types";
import { useTasksStore } from "@/stores/tasks";

const tasks = useTasksStore();
const filter = ref("all");

const chips = computed(() => [
  { value: "all", label: "全部", count: tasks.history.length },
  { value: "retrieved", label: "已取回", count: count("retrieved") },
  { value: "expired", label: "已过期清理", count: count("expired") },
  { value: "deleted", label: "已删除", count: count("deleted") },
  { value: "failed", label: "下载失败", count: count("failed") },
  { value: "canceled", label: "已取消", count: count("canceled") },
]);

function count(status: string): number {
  return tasks.history.filter((task) => task.ui_status === status).length;
}

const filtered = computed(() => {
  if (filter.value === "all") return tasks.history;
  return tasks.history.filter((task) => task.ui_status === filter.value);
});

function shaLabel(task: Task): string {
  return task.sha256 ? shortSha(task.sha256) : "—";
}
</script>

<template>
  <AppShell title="历史">
    <p class="note reveal" style="--i: 0">
      已删除文件不可恢复；SHA-256 会永久保留在记录中，供你核对本地副本。
    </p>

    <section class="toolbar reveal" style="--i: 1">
      <FilterChips v-model="filter" :options="chips" />
      <span class="muted num total">{{ filtered.length }} 条记录</span>
    </section>

    <section class="panel table-panel reveal" style="--i: 2">
      <div class="table-head">
        <span class="col-name">文件名</span>
        <span class="col-size">大小</span>
        <span class="col-status">状态</span>
        <span class="col-sha">SHA-256</span>
        <span class="col-bytes">下载</span>
        <span class="col-bytes">回传</span>
        <span class="col-time">完成时间</span>
      </div>

      <div v-if="filtered.length" class="rows">
        <div v-for="(task, index) in filtered" :key="task.id" class="row row-in" :style="`--i:${index}`">
          <div class="col-name name-cell">
            <div class="name-copy">
              <span class="filename truncate" :title="task.filename">{{ task.filename }}</span>
              <span class="host truncate">{{ task.url_display }}</span>
            </div>
          </div>
          <span class="col-size num">{{ formatBytes(task.file_size) }}</span>
          <span class="col-status"><StatusBadge :status="task.ui_status" /></span>
          <code class="col-sha mono muted truncate" :title="task.sha256 ?? ''">{{ shaLabel(task) }}</code>
          <span class="col-bytes num">{{ formatTraffic(task.download_bytes) }}</span>
          <span class="col-bytes num">{{ formatTraffic(task.retrieved_bytes) }}</span>
          <span class="col-time num muted">{{ formatDateTime(task.completed_at ?? task.created_at) }}</span>
        </div>
      </div>

      <EmptyState
        v-else
        title="还没有历史记录"
        description="取回、过期清理、失败或取消的任务会出现在这里。"

      />
    </section>

    <div v-if="filtered.length" class="mobile-list reveal" style="--i: 2">
      <div v-for="(task, index) in filtered" :key="task.id" class="mobile-card panel row-in" :style="`--i:${index}`">
        <div class="mobile-top">
          <span class="filename truncate">{{ task.filename }}</span>
          <StatusBadge :status="task.ui_status" />
        </div>
        <div class="mobile-meta num">
          <span>{{ formatBytes(task.file_size) }}</span>
          <span>{{ formatDateTime(task.completed_at ?? task.created_at) }}</span>
        </div>
        <div class="mobile-bytes num">
          <span>下载 {{ formatTraffic(task.download_bytes) }}</span>
          <span>回传 {{ formatTraffic(task.retrieved_bytes) }}</span>
        </div>
        <code class="mono muted truncate">{{ shaLabel(task) }}</code>
      </div>
    </div>
  </AppShell>
</template>

<style scoped>
.note {
  margin-bottom: var(--space-4);
  padding: 10px var(--panel-inset);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--bg-surface);
  color: var(--text-secondary);
  font-size: var(--fs-sm);
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: 0 var(--panel-inset);
  margin-bottom: var(--space-4);
}

.total {
  font-size: var(--fs-xs);
  color: var(--text-tertiary);
}

.table-panel {
  overflow: clip;
}

.table-head,
.row {
  display: grid;
  grid-template-columns: minmax(220px, 2.2fr) 84px 104px 150px 88px 88px 112px;
  align-items: center;
  gap: var(--space-3);
  padding: 0 var(--panel-inset);
}

@media (min-width: 2200px) {
  .table-head,
  .row {
    grid-template-columns: minmax(240px, 2.8fr) 0.8fr 0.9fr 1.5fr 0.9fr 0.9fr 0.9fr;
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
.table-head .col-bytes,
.table-head .col-time {
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
.col-bytes,
.col-time {
  text-align: right;
  font-size: var(--fs-sm);
  color: var(--text-secondary);
}

.col-size {
  color: var(--text-primary);
  font-weight: 500;
}

.col-sha {
  font-size: 10.5px;
  min-width: 0;
  color: var(--text-tertiary);
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
    grid-template-columns: minmax(200px, 2fr) 80px 104px 130px 84px 100px;
  }
  .col-time {
    display: none;
  }
}

@media (max-width: 1023px) {
  .table-head,
  .row {
    grid-template-columns: minmax(180px, 2fr) 78px 104px 120px;
  }
  .col-sha,
  .col-bytes:nth-of-type(2) {
    display: none;
  }
}

@media (max-width: 767px) {
  .note {
    padding: 10px 14px;
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
    gap: 8px;
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
  .mobile-meta,
  .mobile-bytes {
    display: flex;
    gap: 12px;
    color: var(--text-tertiary);
    font-size: 11px;
  }
  .mobile-bytes span {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .mobile-card code {
    padding: 2px 6px;
    border-radius: var(--radius-xs);
    background: var(--bg-subtle);
    font-size: 10.5px;
  }
}
</style>