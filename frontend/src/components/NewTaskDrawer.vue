<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

import AppIcon from "@/components/AppIcon.vue";
import UiButton from "@/components/UiButton.vue";
import { ApiError } from "@/services/api";
import { useTasksStore } from "@/stores/tasks";
import { useUiStore } from "@/stores/ui";

const props = defineProps<{ modelValue: boolean }>();
const emit = defineEmits<{
  (event: "update:modelValue", value: boolean): void;
  (event: "created"): void;
}>();

const tasks = useTasksStore();
const ui = useUiStore();

const url = ref("");
const filename = ref("");
const connections = ref<number | null>(null);
const speedMbps = ref<number | null>(null);
const advanced = ref(false);
const submitting = ref(false);
const error = ref("");

watch(
  () => props.modelValue,
  (open) => {
    if (!open) {
      url.value = "";
      filename.value = "";
      connections.value = null;
      speedMbps.value = null;
      advanced.value = false;
      error.value = "";
      submitting.value = false;
    }
  },
);

function close(): void {
  if (!submitting.value) emit("update:modelValue", false);
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") close();
}

onMounted(() => window.addEventListener("keydown", onKeydown));
onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown));

async function submit(): Promise<void> {
  error.value = "";
  const trimmed = url.value.trim();
  if (!trimmed) {
    error.value = "请先粘贴下载链接";
    return;
  }
  if (!/^https?:\/\//i.test(trimmed)) {
    error.value = "链接必须以 http:// 或 https:// 开头";
    return;
  }

  submitting.value = true;
  try {
    const result = await tasks.create({
      url: trimmed,
      filename: filename.value.trim() || null,
      connections: connections.value,
      speed_limit_kib_per_s:
        speedMbps.value !== null && speedMbps.value > 0
          ? Math.round(speedMbps.value * 1024)
          : null,
    });
    if (result.duplicate) {
      ui.notify("info", "该链接已有任务，已为你定位到原任务");
    } else {
      ui.notify("success", "已开始下载");
    }
    emit("created");
    emit("update:modelValue", false);
  } catch (caught) {
    const message = caught instanceof ApiError ? caught.message : "创建任务失败";
    error.value = message;
    ui.notify("error", message);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="drawer">
      <div v-if="modelValue" class="overlay" @click.self="close">
        <aside class="drawer" role="dialog" aria-modal="true" aria-label="新建下载任务">
          <span class="grabber" aria-hidden="true" />
          <header class="head">
            <div class="head-copy">
              <h2 class="title">新建下载</h2>
              <p class="subtitle">VPS 会用自身网络拉取，文件先暂存在服务器</p>
            </div>
            <button type="button" class="icon-btn" aria-label="关闭" @click="close">
              <AppIcon name="x" :size="17" :stroke-width="1.8" />
            </button>
          </header>

          <form class="body" @submit.prevent="submit">
            <div class="field">
              <label for="task-url">下载链接</label>
              <div class="url-wrap">
                <input
                  id="task-url"
                  v-model="url"
                  class="input url-input"
                  type="url"
                  inputmode="url"
                  autocomplete="off"
                  spellcheck="false"
                  placeholder="https://example.com/file.zip"
                  data-testid="new-task-url"
                  autofocus
                />
              </div>
              <span class="hint">支持 http / https，只允许公网地址；内网与云元数据地址会被拦截。</span>
            </div>

            <div class="field">
              <label for="task-filename">自定义文件名 <span class="optional">可选</span></label>
              <input
                id="task-filename"
                v-model="filename"
                class="input"
                maxlength="180"
                placeholder="留空则使用链接中的文件名"
              />
            </div>

            <button type="button" class="advanced-toggle" @click="advanced = !advanced">
              <AppIcon :name="advanced ? 'chevron-down' : 'chevron-right'" :size="14" />
              高级选项
              <span class="advanced-hint">连接数 · 限速</span>
            </button>

            <div v-if="advanced" class="advanced">
              <div class="field-row">
                <div class="field">
                  <label for="task-connections">连接数</label>
                  <input
                    id="task-connections"
                    v-model.number="connections"
                    class="input num"
                    type="number"
                    min="1"
                    max="16"
                    placeholder="4"
                  />
                </div>
                <div class="field">
                  <label for="task-speed">限速（MB/s，0 不限）</label>
                  <input
                    id="task-speed"
                    v-model.number="speedMbps"
                    class="input num"
                    type="number"
                    min="0"
                    step="0.5"
                    placeholder="默认"
                  />
                </div>
              </div>
            </div>

            <p v-if="error" class="form-error" role="alert">{{ error }}</p>

            <div class="actions">
              <UiButton variant="ghost" :disabled="submitting" @click="close">取消</UiButton>
              <UiButton type="submit" variant="primary" :loading="submitting" class="submit">
                开始下载
              </UiButton>
            </div>
          </form>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  z-index: 120;
  display: flex;
  justify-content: flex-end;
  background: var(--overlay);
  backdrop-filter: blur(3px);
}

.drawer {
  position: relative;
  display: flex;
  flex-direction: column;
  width: min(440px, 100%);
  height: 100%;
  background: var(--bg-raised);
  border-left: 1px solid var(--border-subtle);
  box-shadow: var(--shadow-modal);
}

.grabber {
  display: none;
}

.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 24px var(--panel-inset) 18px;
  border-bottom: 1px solid var(--border-subtle);
}

.head-copy {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.title {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.02em;
}

.subtitle {
  font-size: 11.5px;
  color: var(--text-tertiary);
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 32px;
  height: 32px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-surface);
  color: var(--text-secondary);
  cursor: pointer;
}

.icon-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.body {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 22px var(--panel-inset) 24px;
  overflow-y: auto;
}

.url-wrap {
  position: relative;
}

.url-input {
  font-family: var(--font-mono);
  font-size: 12.5px;
}

.optional {
  margin-left: 4px;
  font-size: 10px;
  font-weight: 400;
  color: var(--text-tertiary);
}

.advanced-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  align-self: flex-start;
  padding: 4px 0;
  border: 0;
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--fs-sm);
  font-weight: 500;
  cursor: pointer;
}

.advanced-toggle:hover {
  color: var(--text-primary);
}

.advanced-hint {
  margin-left: 2px;
  font-size: 10.5px;
  color: var(--text-tertiary);
}

.advanced {
  padding: 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--bg-subtle);
}

.form-error {
  padding: 9px 11px;
  border-radius: var(--radius-sm);
  background: var(--danger-soft);
  color: var(--danger);
  font-size: var(--fs-xs);
}

.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: auto;
  padding-top: 18px;
  border-top: 1px solid var(--border-subtle);
}

.submit {
  flex: 1;
}

.drawer-enter-active,
.drawer-leave-active {
  transition: opacity 200ms var(--ease-out);
}

.drawer-enter-active .drawer,
.drawer-leave-active .drawer {
  transition: transform 280ms var(--ease-out);
}

.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}

.drawer-enter-from .drawer,
.drawer-leave-to .drawer {
  transform: translateX(32px);
}

@media (max-width: 767px) {
  .overlay {
    align-items: flex-end;
  }
  .drawer {
    width: 100%;
    height: auto;
    max-height: 92dvh;
    border-left: 0;
    border-top: 1px solid var(--border-subtle);
    border-radius: var(--radius-2xl) var(--radius-2xl) 0 0;
  }
  .grabber {
    display: block;
    width: 36px;
    height: 4px;
    margin: 8px auto 0;
    border-radius: var(--radius-pill);
    background: var(--border-strong);
  }
  .head {
    padding: 16px 20px 14px;
  }
  .body {
    padding: 18px 20px calc(20px + env(safe-area-inset-bottom));
  }
  .drawer-enter-from .drawer,
  .drawer-leave-to .drawer {
    transform: translateY(40px);
  }
}

@media (min-width: 2200px) {
  .drawer {
    width: min(520px, 100%);
  }
}

@media (min-width: 3000px) {
  .drawer {
    width: min(600px, 100%);
  }
}
</style>