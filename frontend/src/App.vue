<template>
  <a-config-provider :theme="themeConfig">
    <a-layout class="app-shell">
      <a-layout-header class="app-header">
        <div class="brand">
          <span class="brand-mark">镇</span>
          <div class="brand-copy">
            <span class="brand-name">镇江旅行助手</span>
            <span class="brand-tag">确定性 DAG · Agent 编排</span>
          </div>
        </div>
        <div class="header-note">JIANGSU · ZHENJIANG</div>
      </a-layout-header>
      <a-layout-content class="app-content">
        <router-view />
      </a-layout-content>
      <a-layout-footer class="app-footer">
        <span>镇江旅行助手</span>
        <span>价格为参考值，出行前请以景区当日公示为准</span>
      </a-layout-footer>
    </a-layout>
  </a-config-provider>
</template>

<script setup lang="ts">
const themeConfig = {
  token: {
    colorPrimary: '#2f5a4a',
    colorLink: '#a94a37',
    colorText: '#22312c',
    colorTextSecondary: '#6f7a72',
    colorBgBase: '#f6f1e7',
    colorBorder: '#ded4c3',
    borderRadius: 4,
    fontFamily:
      "'Inter', 'Noto Sans SC', 'Microsoft YaHei', -apple-system, BlinkMacSystemFont, sans-serif"
  }
}
</script>

<style>
:root {
  --paper: #f6f1e7;
  --paper-deep: #eee6d8;
  --surface: #fffdf8;
  --surface-soft: #fbf7ee;
  --ink: #22312c;
  --ink-soft: #52605a;
  --muted: #7b847c;
  --pine: #2f5a4a;
  --pine-deep: #1f4036;
  --pine-soft: #e5ece6;
  --cinnabar: #a94a37;
  --cinnabar-soft: #f4e4de;
  --gold: #b18b52;
  --line: #ded4c3;
  --line-soft: #ebe3d5;
  --shadow: 0 18px 45px rgba(47, 62, 54, 0.08);
  --serif: 'Noto Serif SC', 'Songti SC', 'STSong', 'SimSun', serif;
  --sans: 'Inter', 'Noto Sans SC', 'Microsoft YaHei', -apple-system, BlinkMacSystemFont,
    sans-serif;
}

html {
  background: var(--paper);
}

body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: var(--sans);
  -webkit-font-smoothing: antialiased;
}

#app {
  min-height: 100vh;
  font-family: var(--sans);
}

.app-shell {
  min-height: 100vh;
  background: transparent;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 68px;
  padding: 0 34px;
  background: rgba(246, 241, 231, 0.96) !important;
  border-bottom: 1px solid var(--line);
  line-height: 1;
  position: sticky;
  top: 0;
  z-index: 100;
  backdrop-filter: blur(14px);
  color: var(--ink) !important;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--ink) !important;
}

.brand-mark {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border: 1px solid var(--cinnabar);
  color: var(--cinnabar);
  font-family: var(--serif);
  font-size: 19px;
  line-height: 1;
}

.brand-copy {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.brand-name {
  font-family: var(--serif);
  font-size: 21px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.brand-tag {
  color: var(--muted);
  font-size: 11px;
  letter-spacing: 0.08em;
}

.header-note {
  color: var(--gold);
  font-size: 10px;
  letter-spacing: 0.22em;
}

.app-content {
  padding: 0;
  background: transparent;
}

.app-footer {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 34px;
  background: transparent !important;
  border-top: 1px solid var(--line);
  color: var(--muted) !important;
  font-size: 11px;
  letter-spacing: 0.04em;
}

.app-footer span:first-child {
  color: var(--ink-soft);
  font-family: var(--serif);
}

@media (max-width: 768px) {
  .app-header {
    padding: 0 18px;
  }

  .brand-copy {
    gap: 6px;
  }

  .brand-tag,
  .header-note {
    display: none;
  }

  .app-footer {
    flex-direction: column;
    padding: 16px 18px;
  }
}
</style>
