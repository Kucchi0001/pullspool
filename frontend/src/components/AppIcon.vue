<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{ name: string; size?: number; strokeWidth?: number }>(),
  { size: 16, strokeWidth: 1.8 },
);

const PATHS: Record<string, string[]> = {
  grid: ["M3 3h7v7H3z", "M14 3h7v7h-7z", "M14 14h7v7h-7z", "M3 14h7v7H3z"],
  download: ["M12 3v12", "m7 10 5 5 5-5", "M5 21h14"],
  inbox: [
    "M22 12h-6l-2 3h-4l-2-3H2",
    "M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z",
  ],
  clock: ["M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18", "M12 7v5l3 2"],
  sliders: ["M4 6h10", "M18 6h2", "M4 12h4", "M12 12h8", "M4 18h12", "M20 18h0", "M14 4v4", "M8 10v4", "M16 16v4"],
  plus: ["M12 5v14", "M5 12h14"],
  play: ["m8 5 11 7-11 7z"],
  pause: ["M9 5v14", "M15 5v14"],
  x: ["M6 6l12 12", "M18 6 6 18"],
  trash: ["M4 7h16", "M9 7V4h6v3", "M6 7l1 13h10l1-13", "M10 11v6", "M14 11v6"],
  refresh: ["M20 12a8 8 0 1 1-2.34-5.66", "M20 4v5h-5"],
  sun: [
    "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8",
    "M12 2v2",
    "M12 20v2",
    "M4 12H2",
    "M22 12h-2",
    "M5 5l1.5 1.5",
    "M17.5 17.5 19 19",
    "M19 5l-1.5 1.5",
    "M6.5 17.5 5 19",
  ],
  moon: ["M21 13a8.5 8.5 0 1 1-10-10 7 7 0 0 0 10 10z"],
  monitor: ["M3 4h18v12H3z", "M8 20h8", "M12 16v4"],
  copy: ["M9 9h10v10H9z", "M5 15V5h10"],
  check: ["m5 12 4 4 10-10"],
  alert: ["M12 3 2 21h20L12 3z", "M12 9v6", "M12 18h.01"],
  more: ["M6 12h.01", "M12 12h.01", "M18 12h.01"],
  "chevron-left": ["m14 6-6 6 6 6"],
  "chevron-right": ["m10 6 6 6-6 6"],
  search: ["M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14", "m20 20-4.35-4.35"],
  logout: ["M15 4h4v16h-4", "M10 12H3", "m7 8-4 4 4 4"],
  external: ["M14 4h6v6", "M20 4 10 14", "M18 14v6H4V6h6"],
  shield: ["M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"],
  link: [
    "M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 1 0-5.66-5.66l-1 1",
    "M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 1 0 5.66 5.66l1-1",
  ],
  menu: ["M4 7h16", "M4 12h16", "M4 17h16"],
  "arrow-left": ["M19 12H5", "m11 6-6 6 6 6"],
  drive: ["M3 12h18", "M5 12V6h14v6", "M4 12h16v6H4z", "M7 15h.01", "M11 15h.01"],
  "hard-drive": ["M3 12h18", "M5 12V6h14v6", "M4 12h16v6H4z", "M7 15h.01", "M11 15h.01"],
  activity: ["M3 12h4l2 6 4-14 2 8h6"],
  warning: ["M12 9v4", "M12 17h.01", "M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"],
  file: ["M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z", "M14 2v6h6"],
  "file-text": [
    "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z",
    "M14 2v6h6",
    "M16 13H8",
    "M16 17H8",
    "M10 9H8",
  ],
  "file-code": [
    "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z",
    "M14 2v6h6",
    "m10 13-2 2 2 2",
    "m14 17 2-2-2-2",
  ],
  "file-image": [
    "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z",
    "M14 2v6h6",
    "m7 17 3-3 3 3 2.5-3 2.5 3",
    "M9 10h.01",
  ],
  "file-video": [
    "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z",
    "M14 2v6h6",
    "m10 12 5 3-5 3z",
  ],
  "file-audio": [
    "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z",
    "M14 2v6h6",
    "M11 18v-5",
    "M14 18v-3",
    "M17 18v-6",
  ],
  package: [
    "m7.5 4.27 9 5.15",
    "M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z",
    "m3.3 7 8.7 5 8.7-5",
    "M12 22V12",
  ],
  server: ["M4 4h16v6H4z", "M4 14h16v6H4z", "M7 7h.01", "M7 17h.01"],
  cpu: [
    "M6 6h12v12H6z",
    "M9 9h6v6H9z",
    "M9 2v4",
    "M15 2v4",
    "M9 18v4",
    "M15 18v4",
    "M2 9h4",
    "M2 15h4",
    "M18 9h4",
    "M18 15h4",
  ],
  gauge: ["M12 14l4-4", "M3.34 19a10 10 0 1 1 17.32 0"],
  "arrow-up-right": ["M7 17 17 7", "M8 7h9v9"],
  calendar: ["M8 2v4", "M16 2v4", "M3 5h18v16H3z", "M3 10h18"],
  "chevron-down": ["m6 9 6 6 6-6"],
  filter: ["M4 5h16l-6 8v6l-4 2v-8z"],
  "shield-check": [
    "M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z",
    "m9 12 2 2 4-4",
  ],
  wifi: ["M5 12a10 10 0 0 1 14 0", "M8.5 15.5a5 5 0 0 1 7 0", "M12 19h.01"],
  database: [
    "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3",
    "M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6",
    "M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6",
  ],
  "cloud-download": ["M12 13v8", "m8 17 4 4 4-4", "M20.5 16.5A4.5 4.5 0 0 0 18 8h-1.3A6 6 0 1 0 6 15.5"],
  info: ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20", "M12 16v-4", "M12 8h.01"],
};

const paths = computed(() => PATHS[props.name] ?? PATHS.activity);
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    class="icon"
  >
    <path v-for="(d, index) in paths" :key="index" :d="d" />
  </svg>
</template>

<style scoped>
.icon {
  display: block;
  flex: none;
}
</style>
