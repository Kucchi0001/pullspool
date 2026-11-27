<script setup lang="ts">
withDefaults(
  defineProps<{
    variant?: "primary" | "secondary" | "ghost" | "danger";
    size?: "sm" | "md";
    type?: "button" | "submit";
    disabled?: boolean;
    loading?: boolean;
    block?: boolean;
  }>(),
  { variant: "secondary", size: "md", type: "button", disabled: false, loading: false, block: false },
);

defineEmits<{ (event: "click", payload: MouseEvent): void }>();
</script>

<template>
  <button
    :type="type"
    class="btn"
    :class="[variant, size, { block, loading }]"
    :disabled="disabled || loading"
    @click="$emit('click', $event)"
  >
    <span v-if="loading" class="spinner" aria-hidden="true" />
    <slot />
  </button>
</template>

<style scoped>
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  height: var(--button-h);
  padding: 0 14px;
  border-radius: var(--radius-md);
  border: 1px solid transparent;
  background: var(--bg-surface);
  color: var(--text-primary);
  font-size: var(--fs-sm);
  font-weight: 550;
  letter-spacing: -0.005em;
  cursor: pointer;
  white-space: nowrap;
  transition: background var(--duration) var(--ease-out),
    border-color var(--duration) var(--ease-out), color var(--duration) var(--ease-out),
    transform var(--duration) var(--ease-out), box-shadow var(--duration) var(--ease-out);
}

.btn:active:not(:disabled) {
  transform: scale(0.985);
}

.btn.sm {
  height: var(--button-h-sm);
  padding: 0 10px;
  font-size: var(--fs-xs);
  border-radius: var(--radius-sm);
}

.btn.block {
  width: 100%;
}

.btn.primary {
  background: var(--accent);
  color: var(--accent-contrast);
  box-shadow: 0 1px 1px rgba(30, 26, 20, 0.12),
    0 8px 18px -12px color-mix(in srgb, var(--accent) 55%, transparent);
}

.btn.primary:hover:not(:disabled) {
  background: var(--accent-hover);
}

.btn.secondary {
  background: var(--bg-raised);
  border-color: var(--border);
}

.btn.secondary:hover:not(:disabled) {
  background: var(--bg-hover);
  border-color: var(--border-strong);
}

.btn.ghost {
  background: transparent;
  color: var(--text-secondary);
}

.btn.ghost:hover:not(:disabled) {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.btn.danger {
  background: var(--danger-soft);
  color: var(--danger);
}

.btn.danger:hover:not(:disabled) {
  background: color-mix(in srgb, var(--danger) 18%, var(--danger-soft));
}

.btn:disabled,
.btn.primary:disabled,
.btn.secondary:disabled,
.btn.ghost:disabled,
.btn.danger:disabled {
  background: var(--bg-subtle);
  border-color: var(--border);
  color: var(--text-tertiary);
  box-shadow: none;
  opacity: 1;
  cursor: not-allowed;
}

.spinner {
  width: 13px;
  height: 13px;
  border: 2px solid currentColor;
  border-right-color: transparent;
  border-radius: 50%;
  animation: spin 700ms linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .spinner {
    animation-duration: 2s;
  }
}
</style>
