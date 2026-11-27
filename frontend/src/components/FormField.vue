<script setup lang="ts">
defineProps<{ label: string; hint?: string }>();
</script>

<template>
  <div class="field">
    <label>{{ label }}</label>
    <slot />
    <span v-if="hint" class="hint">{{ hint }}</span>
  </div>
</template>
