import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { adminApi } from '@/api'
import type { AdminFeatureOut } from '@/types'

export const useAdminStore = defineStore('admin', () => {
  const features = ref<AdminFeatureOut[]>([])
  const loaded = ref(false)
  const loading = ref(false)

  const enabledFeatureCodes = computed(() => new Set(features.value.filter((feature) => feature.enabled).map((feature) => feature.code)))

  async function loadFeatures(force = false) {
    if (loading.value || (loaded.value && !force)) return
    loading.value = true
    try {
      features.value = await adminApi.features()
      loaded.value = true
    } finally {
      loading.value = false
    }
  }

  function isEnabled(code?: string) {
    return !code || !loaded.value || enabledFeatureCodes.value.has(code)
  }

  return { features, loaded, loading, enabledFeatureCodes, loadFeatures, isEnabled }
})
