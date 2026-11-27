<script setup lang="ts">
withDefaults(defineProps<{ title: string; description?: string }>(), { description: "" });
</script>

<template>
  <div class="empty">
    <p class="empty-title">{{ title }}</p>
    <p v-if="description" class="empty-desc">{{ description }}</p>
    <div v-if="$slots.default" class="empty-action">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 188px;
  padding: var(--space-9) var(--space-8);
  text-align: center;
}

.empty-title {
  font-size: 15px;
  font-weight: 550;
  letter-spacing: -0.012em;
}

.empty-desc {
  max-width: 460px;
  font-size: var(--fs-sm);
  line-height: 1.55;
  color: var(--text-secondary);
}

.empty-action {
  margin-top: 10px;
}
</style>
