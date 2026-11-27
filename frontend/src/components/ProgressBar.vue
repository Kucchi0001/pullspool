<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{ value: number | null; status?: string; height?: number }>(),
  { status: "downloading", height: 4 },
);

const width = computed(() => {
  if (props.value === null || Number.isNaN(props.value)) return null;
  return `${Math.max(0, Math.min(1, props.value)) * 100}%`;
});

const tone = computed(() => {
  if (props.status === "completed" || props.status === "ready") return "success";
  if (props.status === "verifying") return "accent";
  if (props.status === "failed") return "danger";
  if (props.status === "paused" || props.status === "queued") return "neutral";
  return "info";
});
</script>

<template>
  <div
    class="track"
    :style="{ height: `${height}px` }"
    role="progressbar"
    :aria-valuenow="value === null ? undefined : Math.round(value * 100)"
    aria-valuemin="0"
    aria-valuemax="100"
  >
    <div v-if="width === null" class="fill indeterminate" :class="tone" />
    <div v-else class="fill" :class="tone" :style="{ width }" />
  </div>
</template>

<style scoped>
.track {
  width: 100%;
  background: var(--bg-subtle);
  border-radius: var(--radius-pill);
  overflow: hidden;
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--border) 45%, transparent);
}

.fill {
  height: 100%;
  border-radius: var(--radius-pill);
  transition: width 500ms var(--ease-out);
}

.fill.info {
  background: var(--accent);
}

.fill.success {
  background: var(--success);
}

.fill.accent {
  background: var(--accent);
}

.fill.danger {
  background: var(--danger);
}

.fill.neutral {
  background: color-mix(in srgb, var(--neutral) 55%, var(--bg-subtle));
}

.fill.indeterminate {
  width: 38%;
  animation: slide 1.4s ease-in-out infinite;
}

@keyframes slide {
  0% {
    margin-left: 0;
  }
  50% {
    margin-left: 62%;
  }
  100% {
    margin-left: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .fill {
    transition: none;
  }
  .fill.indeterminate {
    animation: none;
    width: 100%;
  }
}
</style>
