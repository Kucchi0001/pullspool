<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ page: number; pageSize: number; total: number }>();

const emit = defineEmits<{ (event: "update:page", value: number): void }>();

const pages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)));
const canPrev = computed(() => props.page > 1);
const canNext = computed(() => props.page < pages.value);
</script>

<template>
  <div class="pagination">
    <span class="muted num">共 {{ total }} 条 · 每页 {{ pageSize }}</span>
    <div class="controls">
      <button type="button" :disabled="!canPrev" aria-label="上一页" @click="emit('update:page', page - 1)">
        ‹
      </button>
      <span class="num">{{ page }} / {{ pages }}</span>
      <button type="button" :disabled="!canNext" aria-label="下一页" @click="emit('update:page', page + 1)">
        ›
      </button>
    </div>
  </div>
</template>

<style scoped>
.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  min-height: 40px;
  padding: 0 var(--space-2);
  font-size: var(--fs-sm);
}

.controls {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.controls button {
  width: 26px;
  height: 26px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--bg-surface);
  color: var(--text-secondary);
  cursor: pointer;
}

.controls button:hover:not(:disabled) {
  background: var(--bg-hover);
}

.controls button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
