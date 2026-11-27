<script setup lang="ts">
import { ref } from "vue";

import AppIcon from "@/components/AppIcon.vue";
import { useUiStore } from "@/stores/ui";

const props = withDefaults(defineProps<{ text: string | null; label?: string }>(), { label: "" });

const ui = useUiStore();
const copied = ref(false);

async function copy(): Promise<void> {
  if (!props.text) return;
  try {
    await navigator.clipboard.writeText(props.text);
  } catch {
    const textarea = document.createElement("textarea");
    textarea.value = props.text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    textarea.remove();
  }
  copied.value = true;
  ui.notify("success", "已复制");
  window.setTimeout(() => (copied.value = false), 1200);
}
</script>

<template>
  <button
    type="button"
    class="copy"
    :title="label || '复制'"
    :aria-label="label || '复制'"
    :disabled="!text"
    @click.stop="copy"
  >
    <AppIcon :name="copied ? 'check' : 'copy'" :size="13" />
  </button>
</template>

<style scoped>
.copy {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  vertical-align: middle;
}

.copy:hover:not(:disabled) {
  background: var(--bg-hover);
  color: var(--text-secondary);
}

.copy:disabled {
  opacity: 0.4;
  cursor: default;
}
</style>
