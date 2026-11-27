<script setup lang="ts">
defineProps<{
  modelValue: string;
  options: { value: string; label: string; count?: number }[];
}>();

defineEmits<{ (event: "update:modelValue", value: string): void }>();
</script>

<template>
  <div class="chips" role="tablist">
    <button
      v-for="option in options"
      :key="option.value"
      type="button"
      role="tab"
      class="chip"
      :class="{ active: modelValue === option.value }"
      :aria-selected="modelValue === option.value"
      @click="$emit('update:modelValue', option.value)"
    >
      {{ option.label }}
      <span v-if="option.count !== undefined" class="count num">{{ option.count }}</span>
    </button>
  </div>
</template>

<style scoped>
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  min-width: 0;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 30px;
  padding: 0 10px;
  border-radius: var(--radius-pill);
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--fs-xs);
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  transition: background var(--duration) var(--ease-out), color var(--duration) var(--ease-out),
    border-color var(--duration) var(--ease-out);
}

.chip:hover {
  background: var(--bg-subtle);
  color: var(--text-primary);
}

.chip.active {
  background: var(--accent-soft);
  border-color: color-mix(in srgb, var(--accent) 22%, transparent);
  color: var(--accent);
}

.count {
  min-width: 16px;
  padding: 0 4px;
  border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--text-tertiary) 12%, transparent);
  font-size: 10px;
  line-height: 15px;
  text-align: center;
}

.chip.active .count {
  background: color-mix(in srgb, var(--accent) 16%, transparent);
}
</style>
