<script setup lang="ts">
withDefaults(defineProps<{ label: string; value: string; sub?: string }>(), { sub: "" });
</script>

<template>
  <div class="kpi">
    <span class="label">{{ label }}</span>
    <span :key="value" class="value num">{{ value }}</span>
    <span v-if="sub" class="sub num">{{ sub }}</span>
    <slot />
  </div>
</template>

<style scoped>
.kpi {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding: 22px var(--panel-inset) 20px;
}

.label {
  font-size: var(--fs-xs);
  font-weight: 500;
  letter-spacing: 0.02em;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.value {
  display: inline-block;
  font-size: var(--fs-kpi);
  line-height: var(--lh-kpi);
  font-weight: 550;
  letter-spacing: var(--tracking-tight);
  color: var(--text-primary);
  animation: value-in 220ms var(--ease-out) both;
}

@keyframes value-in {
  from {
    opacity: 0.35;
    transform: translateY(3px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.sub {
  font-size: var(--fs-xs);
  line-height: var(--lh-xs);
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
