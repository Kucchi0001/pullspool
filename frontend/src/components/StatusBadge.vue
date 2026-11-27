<script setup lang="ts">
import { computed } from "vue";

import type { UiStatus } from "@/services/types";

const props = defineProps<{ status: UiStatus | string }>();

const LABELS: Record<string, string> = {
  downloading: "下载中",
  queued: "等待中",
  paused: "已暂停",
  verifying: "校验中",
  transferring: "正在回传",
  ready: "等待取回",
  retrieved: "已取回",
  deleted: "已删除",
  expired: "已过期清理",
  failed: "下载失败",
  canceled: "已取消",
};

const TONES: Record<string, string> = {
  downloading: "info",
  queued: "neutral",
  paused: "neutral",
  verifying: "info pulse",
  transferring: "info",
  ready: "success",
  retrieved: "success",
  deleted: "neutral",
  expired: "warning",
  failed: "danger",
  canceled: "neutral",
};

const label = computed(() => LABELS[props.status] ?? props.status);
const tone = computed(() => TONES[props.status] ?? "neutral");
</script>

<template>
  <span class="badge" :class="tone">
    <span class="dot" aria-hidden="true" />
    {{ label }}
  </span>
</template>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 22px;
  padding: 0 9px;
  border-radius: var(--radius-pill);
  font-size: 11px;
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
}

.dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}

.info {
  color: var(--accent);
  background: var(--accent-soft);
}

.success {
  color: var(--success);
  background: var(--success-soft);
}

.neutral {
  color: var(--text-secondary);
  background: var(--neutral-soft);
}

.warning {
  color: var(--warning);
  background: var(--warning-soft);
}

.danger {
  color: var(--danger);
  background: var(--danger-soft);
}

.pulse .dot {
  animation: pulse 1.8s ease-in-out infinite;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.25;
  }
}

@media (prefers-reduced-motion: reduce) {
  .pulse .dot {
    animation: none;
  }
}
</style>
