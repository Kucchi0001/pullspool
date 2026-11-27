import { createPinia } from "pinia";
import { createApp } from "vue";

import "@fontsource-variable/inter/index.css";
import App from "./App.vue";
import router from "./router";
import "./styles/tokens.css";
import "./styles/base.css";

const app = createApp(App);
app.use(createPinia());
app.use(router);
app.mount("#app");
