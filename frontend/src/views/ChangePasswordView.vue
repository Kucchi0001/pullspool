<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";

import UiButton from "@/components/UiButton.vue";
import { ApiError } from "@/services/api";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";

const auth = useAuthStore();
const ui = useUiStore();
const router = useRouter();

const current = ref("");
const next = ref("");
const confirm = ref("");
const error = ref("");
const submitting = ref(false);

const strongEnough = computed(
  () => next.value.length >= 10 && /[A-Za-z]/.test(next.value) && /\d/.test(next.value),
);

async function submit(): Promise<void> {
  error.value = "";
  if (!current.value) {
    error.value = "请输入当前密码";
    return;
  }
  if (!strongEnough.value) {
    error.value = "新密码至少 10 位，且需同时包含字母与数字";
    return;
  }
  if (next.value !== confirm.value) {
    error.value = "两次输入的新密码不一致";
    return;
  }

  submitting.value = true;
  try {
    await auth.changePassword(current.value, next.value);
    ui.notify("success", "密码已更新");
    await router.replace({ name: "overview" });
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "修改失败，请重试";
  } finally {
    submitting.value = false;
  }
}

async function signOut(): Promise<void> {
  await auth.logout();
  await router.replace({ name: "login" });
}
</script>

<template>
  <div class="page">
    <div class="card">
      <div class="brand">
        <div>
          <h1 class="title">设置新密码</h1>
          <p class="subtitle">首次登录必须修改初始密码后才能使用其他功能</p>
        </div>
      </div>

      <form class="form" @submit.prevent="submit">
        <div class="field">
          <label for="current">当前密码</label>
          <input id="current" v-model="current" class="input" type="password" autocomplete="current-password" />
        </div>
        <div class="field">
          <label for="next">新密码</label>
          <input id="next" v-model="next" class="input" type="password" autocomplete="new-password" data-testid="new-password" />
          <span class="hint">至少 10 位，需同时包含字母与数字。</span>
        </div>
        <div class="field">
          <label for="confirm">确认新密码</label>
          <input id="confirm" v-model="confirm" class="input" type="password" autocomplete="new-password" />
        </div>

        <p v-if="error" class="error-text" role="alert">{{ error }}</p>

        <UiButton type="submit" variant="primary" block :loading="submitting">保存并继续</UiButton>
      </form>

      <button type="button" class="signout" @click="signOut">返回登录</button>
    </div>
  </div>
</template>

<style scoped>
.page {
  display: grid;
  place-items: center;
  min-height: 100dvh;
  padding: var(--space-6);
  background:
    radial-gradient(680px 420px at 16% 8%, color-mix(in srgb, var(--brand) 9%, transparent), transparent 70%),
    radial-gradient(760px 520px at 88% 92%, color-mix(in srgb, var(--accent) 7%, transparent), transparent 72%),
    var(--bg-canvas);
}

.card {
  animation: rise-in 520ms var(--ease-out) both;
  width: min(430px, 100%);
  padding: 34px 32px 26px;
  border: 1px solid var(--border);
  border-radius: var(--radius-2xl);
  background: var(--bg-raised);
  box-shadow: var(--shadow-card);
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 26px;
}

.title {
  font-size: 21px;
  font-weight: 600;
  line-height: 28px;
  letter-spacing: -0.02em;
}

.subtitle {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-tertiary);
}

.form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form :deep(.field > label) {
  font-size: 12px;
  color: var(--text-secondary);
}

.form :deep(.input) {
  height: 42px;
}

.form :deep(.btn) {
  height: 42px;
  font-size: 14px;
}

.signout {
  margin-top: 18px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text-tertiary);
  font-size: var(--fs-xs);
  cursor: pointer;
}

.signout:hover {
  color: var(--text-primary);
}

@media (max-width: 480px) {
  .page {
    padding: 16px;
  }
  .card {
    padding: 26px 20px 20px;
    border-radius: var(--radius-xl);
  }
  .title {
    font-size: 19px;
  }
}

@media (min-width: 2200px) {
  .card {
    width: min(520px, 100%);
    padding: 40px 38px 30px;
  }
  .title {
    font-size: 24px;
    line-height: 31px;
  }
}

@media (min-width: 3000px) {
  .card {
    width: min(580px, 100%);
    padding: 46px 44px 34px;
  }
  .title {
    font-size: 26px;
    line-height: 33px;
  }
}

@media (min-width: 3600px) {
  .card {
    width: min(640px, 100%);
    padding: 52px 50px 38px;
  }
  .title {
    font-size: 28px;
    line-height: 35px;
  }
}
</style>