<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import BrandLogo from "@/components/BrandLogo.vue";
import UiButton from "@/components/UiButton.vue";
import { ApiError } from "@/services/api";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const router = useRouter();
const route = useRoute();

const username = ref("admin");
const password = ref("");
const error = ref("");
const submitting = ref(false);

async function submit(): Promise<void> {
  if (!username.value.trim() || !password.value) {
    error.value = "请输入用户名和密码";
    return;
  }
  error.value = "";
  submitting.value = true;
  try {
    const user = await auth.login(username.value.trim(), password.value);
    if (user.must_change_password) {
      await router.replace({ name: "change-password" });
      return;
    }
    const next = typeof route.query.next === "string" ? route.query.next : "/";
    await router.replace(next.startsWith("/") ? next : "/");
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "登录失败，请重试";
    password.value = "";
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="page">
    <div class="card">
      <div class="brand">
        <BrandLogo :size="56" />
        <div>
          <h1 class="title">PullSpool</h1>
          <p class="subtitle">VPS 远程下载与文件回传</p>
        </div>
      </div>

      <form class="form" @submit.prevent="submit">
        <div class="field">
          <label for="username">用户名</label>
          <input
            id="username"
            v-model="username"
            class="input"
            autocomplete="username"
            spellcheck="false"
            data-testid="login-username"
          />
        </div>
        <div class="field">
          <label for="password">密码</label>
          <input
            id="password"
            v-model="password"
            class="input"
            type="password"
            autocomplete="current-password"
            data-testid="login-password"
          />
        </div>

        <p v-if="error" class="error-text" role="alert" data-testid="login-error">{{ error }}</p>

        <UiButton type="submit" variant="primary" block :loading="submitting" data-testid="login-submit">
          登录
        </UiButton>
      </form>

      <p class="footnote">这是自托管服务，仅限授权用户访问。首次部署默认账号 admin / admin，登录后必须修改密码。</p>
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
  width: min(400px, 100%);
  padding: 36px 34px 28px;
  border: 1px solid var(--border);
  border-radius: var(--radius-2xl);
  background: var(--bg-raised);
  box-shadow: var(--shadow-card);
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 28px;
}

.title {
  font-size: 23px;
  font-weight: 600;
  line-height: 30px;
  letter-spacing: -0.025em;
}

.subtitle {
  margin-top: 3px;
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

.footnote {
  margin-top: 22px;
  padding-top: 16px;
  border-top: 1px solid var(--border-subtle);
  font-size: 10.5px;
  line-height: 1.6;
  color: var(--text-tertiary);
}

@media (max-width: 480px) {
  .page {
    padding: 16px;
    align-items: center;
  }
  .card {
    padding: 28px 22px 22px;
    border-radius: var(--radius-xl);
  }
  .title {
    font-size: 21px;
  }
}

@media (min-width: 2200px) {
  .brand {
    --brand-logo-h: 64px;
  }
  .card {
    width: min(500px, 100%);
    padding: 44px 40px 32px;
  }
  .brand {
    margin-bottom: 32px;
  }
  .title {
    font-size: 26px;
    line-height: 32px;
  }
  .subtitle {
    font-size: 13px;
  }
}

@media (min-width: 3000px) {
  .brand {
    --brand-logo-h: 72px;
  }
  .card {
    width: min(560px, 100%);
    padding: 52px 46px 38px;
  }
  .title {
    font-size: 28px;
    line-height: 34px;
  }
}

@media (min-width: 3600px) {
  .brand {
    --brand-logo-h: 80px;
  }
  .card {
    width: min(620px, 100%);
    padding: 58px 52px 42px;
  }
  .title {
    font-size: 30px;
    line-height: 36px;
  }
}
</style>