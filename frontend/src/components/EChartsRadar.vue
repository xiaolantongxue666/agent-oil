<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { RadarChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import type { AbilityItem } from '@/types'

use([CanvasRenderer, RadarChart, TooltipComponent, LegendComponent])

const props = defineProps<{
  abilities: AbilityItem[]
  height?: string
}>()

const option = computed(() => {
  const names = props.abilities.map((a) => a.name)
  const scores = props.abilities.map((a) => a.score)
  return {
    tooltip: { trigger: 'item' },
    radar: {
      indicator: names.map((n, i) => ({ name: n, max: 100 })),
      shape: 'polygon' as const,
      splitNumber: 4,
      axisName: { color: '#5a6a7d', fontSize: 12 },
      splitArea: { areaStyle: { color: ['#f5f7fa', '#fff'] } },
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            value: scores,
            name: '能力得分',
            areaStyle: { color: 'rgba(11, 95, 107, 0.25)' },
            lineStyle: { color: '#0b5f6b', width: 2 },
            itemStyle: { color: '#0b5f6b' },
          },
        ],
      },
    ],
  }
})
</script>

<template>
  <VChart :option="option" :style="{ height: height || '320px', width: '100%' }" autoresize />
</template>
