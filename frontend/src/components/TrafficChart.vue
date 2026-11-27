<script setup lang="ts">
import { computed, ref } from "vue";

import { formatTraffic } from "@/services/format";
import type { TrafficDay } from "@/services/types";

const props = defineProps<{ days: TrafficDay[] }>();

const CHART_W = 1000;
const CHART_H = 160;
const PAD = 6;

const count = computed(() => props.days.length);
const hasData = computed(() =>
  props.days.some((day) => day.download_bytes > 0 || day.upload_bytes > 0),
);

const maxBytes = computed(() =>
  Math.max(1, ...props.days.flatMap((day) => [day.download_bytes, day.upload_bytes])),
);

const maxMb = computed(() => maxBytes.value / (1024 * 1024));
const axisMaxMb = computed(() => {
  const target = maxMb.value * 1.1;
  const step = target >= 400 ? 100 : target >= 120 ? 50 : target >= 20 ? 10 : 5;
  return Math.max(10, Math.ceil(target / step) * step);
});
const axisMaxBytes = computed(() => axisMaxMb.value * 1024 * 1024);

const yTicks = computed(() => [axisMaxMb.value, axisMaxMb.value / 2, 0]);

function xAt(index: number): number {
  if (count.value <= 1) return 0;
  return (index / (count.value - 1)) * CHART_W;
}

function yAt(bytes: number): number {
  return PAD + (1 - bytes / axisMaxBytes.value) * (CHART_H - PAD * 2);
}

function linePath(values: number[]): string {
  return values
    .map((value, index) => `${index === 0 ? "M" : "L"} ${xAt(index).toFixed(2)} ${yAt(value).toFixed(2)}`)
    .join(" ");
}

const downloadPath = computed(() => linePath(props.days.map((day) => day.download_bytes)));
const uploadPath = computed(() => linePath(props.days.map((day) => day.upload_bytes)));
const downloadArea = computed(() => {
  if (!props.days.length) return "";
  return `${downloadPath.value} L ${CHART_W} ${CHART_H - PAD} L 0 ${CHART_H - PAD} Z`;
});

const labelIndexes = computed(() => {
  const n = count.value;
  if (n <= 7) return props.days.map((_, index) => index);
  return [...new Set([0, Math.round((n - 1) / 3), Math.round(((n - 1) * 2) / 3), n - 1])];
});

function labelFor(index: number): string {
  const day = props.days[index];
  return day ? day.date.slice(5).replace("-", "/") : "";
}

const activeIndex = ref<number | null>(null);
const activeDay = computed(() =>
  activeIndex.value === null ? null : props.days[activeIndex.value] ?? null,
);
const activeX = computed(() =>
  activeIndex.value === null || count.value <= 1
    ? 0
    : (activeIndex.value / (count.value - 1)) * 100,
);
const activeDownTop = computed(() =>
  activeDay.value ? (yAt(activeDay.value.download_bytes) / CHART_H) * 100 : 0,
);
const activeUpTop = computed(() =>
  activeDay.value ? (yAt(activeDay.value.upload_bytes) / CHART_H) * 100 : 0,
);

function onMove(event: PointerEvent): void {
  const element = event.currentTarget as HTMLElement;
  const rect = element.getBoundingClientRect();
  if (rect.width <= 0) return;
  const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
  activeIndex.value = Math.round(ratio * (count.value - 1));
}

function clearActive(): void {
  activeIndex.value = null;
}
</script>

<template>
  <div class="chart">
    <div class="chart-head">
      <div class="legend">
        <span class="legend-item"><i class="legend-line down" />下载</span>
        <span class="legend-item"><i class="legend-line up" />回传</span>
      </div>
      <span class="unit">单位 MB</span>
    </div>

    <div class="chart-main">
      <div class="y-axis num" aria-hidden="true">
        <span v-for="tick in yTicks" :key="tick">{{ tick === 0 ? "0 MB" : `${Math.round(tick)} MB` }}</span>
      </div>

      <div class="plot-shell">
        <div
          class="plot"
          role="img"
          aria-label="近 14 天下载与回传流量折线图，单位 MB"
          @pointermove="onMove"
          @pointerleave="clearActive"
        >

          <svg class="lines" :viewBox="`0 0 ${CHART_W} ${CHART_H}`" preserveAspectRatio="none" aria-hidden="true">
            <g class="grid-lines">
              <line x1="0" :y1="PAD" :x2="CHART_W" :y2="PAD" />
              <line x1="0" :y1="CHART_H / 2" :x2="CHART_W" :y2="CHART_H / 2" />
              <line x1="0" :y1="CHART_H - PAD" :x2="CHART_W" :y2="CHART_H - PAD" />
            </g>
            <defs>
              <linearGradient id="traffic-down-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="var(--accent)" stop-opacity="0.14" />
                <stop offset="100%" stop-color="var(--accent)" stop-opacity="0" />
              </linearGradient>
            </defs>
            <path v-if="hasData" :d="downloadArea" fill="url(#traffic-down-fill)" />
            <path
              v-if="hasData"
              class="line down"
              :d="downloadPath"
              vector-effect="non-scaling-stroke"
            />
            <path
              v-if="hasData"
              class="line up"
              :d="uploadPath"
              vector-effect="non-scaling-stroke"
            />
          </svg>

          <template v-if="activeDay">
            <span class="guide" :style="{ left: `${activeX}%` }" />
            <span class="point down" :style="{ left: `${activeX}%`, top: `${activeDownTop}%` }" />
            <span class="point up" :style="{ left: `${activeX}%`, top: `${activeUpTop}%` }" />
            <div
              class="tip"
              :class="{ 'tip-right': activeX > 68 }"
              :style="{ left: `${Math.min(90, Math.max(10, activeX))}%` }"
            >
              <span class="tip-date">{{ activeDay.date.slice(5).replace("-", "/") }}</span>
              <span class="tip-row">
                <i class="legend-line down" />
                下载 <strong class="num">{{ formatTraffic(activeDay.download_bytes) }}</strong>
              </span>
              <span class="tip-row">
                <i class="legend-line up" />
                回传 <strong class="num">{{ formatTraffic(activeDay.upload_bytes) }}</strong>
              </span>
            </div>
          </template>

          <span v-if="!hasData" class="no-data">近 14 天暂无流量</span>
        </div>

        <div class="x-axis" aria-hidden="true">
          <span
            v-for="index in labelIndexes"
            :key="index"
            class="tick num"
            :class="{ first: index === 0, last: index === count - 1 }"
            :style="{ left: `${count <= 1 ? 0 : (index / (count - 1)) * 100}%` }"
          >
            {{ labelFor(index) }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chart {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.chart-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.legend {
  display: flex;
  gap: 16px;
  font-size: 10.5px;
  color: var(--text-tertiary);
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.legend-line {
  display: inline-block;
  width: 13px;
  height: 2px;
  border-radius: 2px;
}

.legend-line.down {
  background: var(--accent);
}

.legend-line.up {
  background: var(--success);
}

.unit {
  font-size: 9.5px;
  letter-spacing: 0.04em;
  color: var(--text-tertiary);
}

.chart-main {
  display: flex;
  gap: 10px;
}

.y-axis {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  flex: none;
  width: 44px;
  height: 160px;
  padding: 1px 0;
  text-align: right;
  font-size: 9px;
  line-height: 1;
  color: var(--text-tertiary);
}

.plot-shell {
  flex: 1;
  min-width: 0;
}

.plot {
  position: relative;
  height: 160px;
  cursor: crosshair;
  touch-action: pan-y;
}

.grid-lines line {
  stroke: var(--border-subtle);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}

.lines {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: visible;
  pointer-events: none;
}

.line {
  fill: none;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.6;
}

.line.down {
  stroke: var(--accent);
}

.line.up {
  stroke: var(--success);
  stroke-width: 1.3;
}

.guide {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: color-mix(in srgb, var(--text-tertiary) 38%, transparent);
  pointer-events: none;
}

.point {
  position: absolute;
  width: 6px;
  height: 6px;
  border: 2px solid var(--bg-surface);
  border-radius: 50%;
  transform: translate(-50%, -50%);
  pointer-events: none;
}

.point.down {
  background: var(--accent);
}

.point.up {
  background: var(--success);
}

.tip {
  position: absolute;
  top: 2px;
  z-index: 2;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 132px;
  padding: 9px 11px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-raised);
  box-shadow: var(--shadow-pop);
  transform: translateX(-50%);
  pointer-events: none;
}

.tip-right {
  transform: translateX(-100%);
}

.tip-date {
  margin-bottom: 2px;
  font-size: 10px;
  color: var(--text-tertiary);
}

.tip-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.tip-row strong {
  margin-left: auto;
  color: var(--text-primary);
  font-weight: 550;
}

.no-data {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 11px;
  color: var(--text-tertiary);
}

.x-axis {
  position: relative;
  height: 18px;
  margin-top: 2px;
}

.tick {
  position: absolute;
  top: 2px;
  transform: translateX(-50%);
  font-size: 9.5px;
  color: var(--text-tertiary);
  white-space: nowrap;
}

.tick.first {
  transform: none;
}

.tick.last {
  transform: translateX(-100%);
}

@media (max-width: 767px) {
  .y-axis {
    width: 38px;
  }
  .plot {
    height: 142px;
  }
  .y-axis {
    height: 142px;
  }
}
</style>
