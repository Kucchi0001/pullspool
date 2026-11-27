<script setup lang="ts">
import { onBeforeUnmount, onMounted } from "vue";

import UiButton from "@/components/UiButton.vue";

const props = withDefaults(
  defineProps<{
    modelValue: boolean;
    title: string;
    message?: string;
    confirmText?: string;
    cancelText?: string;
    danger?: boolean;
    loading?: boolean;
  }>(),
  {
    message: "",
    confirmText: "确认",
    cancelText: "取消",
    danger: true,
    loading: false,
  },
);

const emit = defineEmits<{
  (event: "update:modelValue", value: boolean): void;
  (event: "confirm"): void;
}>();

function close(): void {
  if (!props.loading) emit("update:modelValue", false);
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") close();
}

onMounted(() => window.addEventListener("keydown", onKeydown));
onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown));
</script>

<template>
  <Teleport to="body">
    <Transition name="dialog">
      <div v-if="modelValue" class="overlay" @click.self="close">
        <div class="dialog" role="dialog" aria-modal="true" :aria-label="title">
          <h2 class="title">{{ title }}</h2>
          <p v-if="message" class="message">{{ message }}</p>
          <slot />
          <div class="actions">
            <UiButton variant="ghost" :disabled="loading" @click="close">{{ cancelText }}</UiButton>
            <UiButton
              :variant="danger ? 'danger' : 'primary'"
              :loading="loading"
              @click="$emit('confirm')"
            >
              {{ confirmText }}
            </UiButton>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  z-index: 150;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-6);
  background: var(--overlay);
  backdrop-filter: blur(3px);
}

.dialog {
  width: min(460px, 100%);
  padding: 26px;
  border-radius: var(--radius-2xl);
  background: var(--bg-raised);
  border: 1px solid var(--border-subtle);
  box-shadow: var(--shadow-modal);
}

.title {
  font-size: 17px;
  font-weight: 600;
  line-height: 25px;
  letter-spacing: -0.02em;
}

.message {
  margin-top: 8px;
  color: var(--text-secondary);
  font-size: var(--fs-sm);
  line-height: 1.6;
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: var(--space-7);
}

.dialog-enter-active,
.dialog-leave-active {
  transition: opacity 180ms var(--ease-out);
}

.dialog-enter-active .dialog,
.dialog-leave-active .dialog {
  transition: transform 220ms var(--ease-out), opacity 180ms var(--ease-out);
}

.dialog-enter-from,
.dialog-leave-to {
  opacity: 0;
}

.dialog-enter-from .dialog,
.dialog-leave-to .dialog {
  opacity: 0;
  transform: translateY(8px) scale(0.98);
}

@media (min-width: 2200px) {
  .dialog {
    width: min(520px, 100%);
    padding: 30px;
  }
}

@media (min-width: 3000px) {
  .dialog {
    width: min(600px, 100%);
    padding: 34px;
  }
}
</style>