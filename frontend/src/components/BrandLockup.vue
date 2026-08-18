<script setup lang="ts">
withDefaults(defineProps<{
  subtitle: string
  inverted?: boolean
  large?: boolean
}>(), {
  inverted: false,
  large: false,
})
</script>

<template>
  <div class="brand-lockup" :class="{ inverted, large }">
    <span class="brand-symbol" aria-hidden="true">
      <el-icon><School /></el-icon>
      <i />
    </span>
    <span class="brand-copy">
      <strong>油训智安</strong>
      <small>{{ subtitle }}</small>
    </span>
  </div>
</template>

<style scoped>
.brand-lockup { display: flex; align-items: center; gap: 12px; min-width: 0; color: var(--ots-primary-dark); }
.brand-symbol { position: relative; display: grid; place-items: center; width: 40px; height: 40px; border: 1px solid var(--ots-border-strong); border-radius: 12px; background: #edf6f6; color: var(--ots-primary); font-size: 22px; flex: 0 0 auto; }
.brand-symbol i { position: absolute; right: -2px; bottom: -2px; width: 10px; height: 10px; border: 2px solid #fff; border-radius: 50%; background: var(--ots-growth); }
.brand-copy { display: block; min-width: 0; }
.brand-copy strong,.brand-copy small { display: block; }
.brand-copy strong { font-size: 19px; letter-spacing: 1px; }
.brand-copy small { margin-top: 4px; overflow: hidden; color: var(--ots-text-secondary); font-size: 10px; line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; }
.inverted { color: #fff; }
.inverted .brand-symbol { border-color: rgba(255,255,255,.25); background: rgba(255,255,255,.1); color: #fff; }
.inverted .brand-copy small { color: rgba(255,255,255,.68); }
.inverted .brand-symbol i { border-color: #0b5963; background: #8adeb3; }
.large { gap: 15px; }
.large .brand-symbol { width: 52px; height: 52px; border-radius: 15px; font-size: 27px; }
.large .brand-copy strong { font-size: 25px; letter-spacing: 2px; }
.large .brand-copy small { margin-top: 5px; font-size: 12px; }

@media (max-width: 768px) {
  .brand-lockup:not(.large) .brand-copy { display: none; }
}
</style>
