<template>
  <div id="app">
    <a-layout style="min-height: 100vh">
      <a-layout-header class="app-header">
        <div class="brand">
          <span class="brand-icon">🧭</span>
          <span class="brand-name">镇江旅行助手</span>
          <span class="brand-tag">确定性 DAG · Agent 编排</span>
        </div>
      </a-layout-header>
      <a-layout-content class="app-content">
        <router-view />
      </a-layout-content>
      <a-layout-footer class="app-footer">
        镇江旅行助手 · 价格为参考值，出行前请以景区当日公示为准
      </a-layout-footer>
    </a-layout>
  </div>
</template>

<script setup lang="ts">
</script>

<style>
#app {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial,
    'Noto Sans', sans-serif;
}

.app-header {
  display: flex;
  align-items: center;
  height: 58px;
  padding: 0 28px;
  background: #101a3a;
  line-height: 58px;
  position: sticky;
  top: 0;
  z-index: 100;
}

.brand {
  display: flex;
  align-items: baseline;
  gap: 10px;
  color: #fff;
}

.brand-icon {
  font-size: 22px;
}

.brand-name {
  font-size: 19px;
  font-weight: 700;
  letter-spacing: 1px;
}

.brand-tag {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.6);
}

.app-content {
  padding: 0;
}

.app-footer {
  padding: 12px;
  background: #101a3a;
  color: rgba(255, 255, 255, 0.5);
  font-size: 12px;
  text-align: center;
}

@media (max-width: 768px) {
  .app-header {
    padding: 0 14px;
  }

  .brand-tag {
    display: none;
  }
}
</style>
