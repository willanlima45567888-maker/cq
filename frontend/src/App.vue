<script setup lang="ts">
import { RouterView, useRoute, useRouter } from 'vue-router'
import { computed } from 'vue'

const route = useRoute()
const router = useRouter()

/** 非首页显示返回链接（"OSW-View · iostat" 之类的二级标题） */
const isHome = computed(() => route.name === 'home')
const pageTitle = computed(() => {
  switch (route.name) {
    case 'iostat': return 'iostat'
    case 'ps': return 'ps'
    case 'top': return 'top'
    case 'netstat': return 'netstat'
    case 'home': return ''
    default: return String(route.name ?? '')
  }
})

function goHome() {
  router.push({ name: 'home' })
}
</script>

<template>
  <div class="app-shell">
    <header v-if="!isHome" class="topbar">
      <button class="back-link" @click="goHome" title="返回首页">
        ← OSW-View
      </button>
      <span class="separator">/</span>
      <span class="page-title">{{ pageTitle }}</span>
    </header>
    <main>
      <RouterView />
    </main>
  </div>
</template>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: #f5f5f5;
  color: #333;
}
</style>

<style scoped>
.app-shell {
  min-height: 100vh;
}
.topbar {
  background: #fff;
  border-bottom: 1px solid #e5e7eb;
  padding: 10px 24px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}
.back-link {
  background: none;
  border: none;
  color: #2563eb;
  cursor: pointer;
  font-size: 14px;
  padding: 4px 8px;
  border-radius: 4px;
  font-family: inherit;
}
.back-link:hover {
  background: #eff6ff;
}
.separator {
  color: #d1d5db;
}
.page-title {
  color: #1f2937;
  font-weight: 500;
}
</style>
