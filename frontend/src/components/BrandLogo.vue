<script setup lang="ts">
withDefaults(defineProps<{ size?: number }>(), { size: 38 });
</script>

<template>
  <img
    class="brand-logo"
    src="/brand/pullspool-mark.png"
    alt=""
    draggable="false"
    :style="{ height: `var(--brand-logo-h, ${size}px)` }"
  />
</template>

<style scoped>
.brand-logo {
  display: block;
  flex: none;
  width: auto;
  max-width: none;
  object-fit: contain;
}
</style>
