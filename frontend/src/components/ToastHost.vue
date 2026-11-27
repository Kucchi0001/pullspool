<script setup lang="ts">
import AppIcon from "@/components/AppIcon.vue";
import { useUiStore } from "@/stores/ui";

const ui = useUiStore();
</script>

<template>
  <div class="toast-host" aria-live="polite">
    <TransitionGroup name="toast">
      <div
        v-for="toast in ui.toasts"
        :key="toast.id"
        class="toast"
        :class="toast.level"
        role="status"
        @click="ui.dismiss(toast.id)"
      >
        <span class="toast-icon">
          <AppIcon
            :name="toast.level === 'success' ? 'check' : toast.level === 'error' ? 'alert' : 'activity'"
            :size="13"
            :stroke-width="2"
          />
        </span>
        <span class="toast-text">{{ toast.message }}</span>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-host {
  position: fixed;
  top: 16px;
  right: 16px;
  z-index: 200;
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: min(360px, calc(100vw - 32px));
  pointer-events: none;
}

.toast {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 13px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--border);
  background: var(--bg-raised);
  box-shadow: var(--shadow-pop);
  font-size: var(--fs-sm);
  color: var(--text-primary);
  pointer-events: auto;
  cursor: pointer;
}

.toast-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 22px;
  height: 22px;
  border-radius: var(--radius-xs);
  background: var(--neutral-soft);
  color: var(--text-secondary);
}

.toast.success .toast-icon {
  background: var(--success-soft);
  color: var(--success);
}

.toast.error .toast-icon {
  background: var(--danger-soft);
  color: var(--danger);
}

.toast.warning .toast-icon {
  background: var(--warning-soft);
  color: var(--warning);
}

.toast-text {
  min-width: 0;
  line-height: 1.4;
}

.toast-enter-active,
.toast-leave-active {
  transition: opacity 200ms var(--ease-out), transform 240ms var(--ease-out);
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.98);
}

@media (max-width: 767px) {
  .toast-host {
    top: auto;
    bottom: 76px;
    left: 16px;
    right: 16px;
    width: auto;
  }
}
</style>
