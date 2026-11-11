<template>
  <a-card id="trace" title="🧭 Agent 执行轨迹" :bordered="false" class="trace-card">
    <template #extra>
      <a-tag color="blue">{{ trace.length }} nodes</a-tag>
    </template>

    <a-empty v-if="trace.length === 0" description="暂无 Trace" />
    <a-timeline v-else>
      <a-timeline-item
        v-for="event in trace"
        :key="event.node_id"
        :color="statusColor(event.status)"
      >
        <div class="trace-head">
          <strong>{{ nodeLabel(event.node_id) }}</strong>
          <a-tag :color="statusColor(event.status)">{{ statusLabel(event.status) }}</a-tag>
          <span class="trace-ms">{{ event.duration_ms.toFixed(0) }} ms</span>
          <a-tag v-if="event.cache" color="cyan">cache: {{ event.cache }}</a-tag>
          <a-tag v-if="tokenLabel(event)" color="purple">tokens: {{ tokenLabel(event) }}</a-tag>
          <a-tag v-if="plannerAttempts(event)" color="orange">
            planner attempts: {{ plannerAttempts(event) }}
          </a-tag>
        </div>
        <div v-if="event.error" class="trace-error">{{ event.error }}</div>
        <div v-if="metaSummary(event)" class="trace-meta">{{ metaSummary(event) }}</div>
      </a-timeline-item>
    </a-timeline>
  </a-card>
</template>

<script setup lang="ts">
import type { TraceEvent } from '@/types'

defineProps<{
  trace: TraceEvent[]
}>()

const nodeLabels: Record<string, string> = {
  load_dataset: '加载镇江数据',
  plan: 'Planner 规划',
  fake_plan: '规则规划（基线）',
  validate: '约束校验',
  budget: '预算计算',
  render: '渲染结果'
}

function nodeLabel(nodeId: string): string {
  return nodeLabels[nodeId] || nodeId
}

function statusColor(status: string): string {
  return {
    ok: 'green',
    degraded: 'orange',
    failed: 'red',
    skipped: 'gray'
  }[status] || 'gray'
}

function statusLabel(status: string): string {
  return {
    ok: '成功',
    degraded: '降级',
    failed: '失败',
    skipped: '跳过'
  }[status] || status
}

function tokenLabel(event: TraceEvent): string {
  const total = event.meta?.total_tokens
  if (typeof total === 'number' && total > 0) return String(total)
  const sum = (event.tokens_in || 0) + (event.tokens_out || 0)
  return sum > 0 ? String(sum) : ''
}

function plannerAttempts(event: TraceEvent): string {
  const attempts = event.meta?.planner_attempts
  return typeof attempts === 'number' ? String(attempts) : ''
}

function metaSummary(event: TraceEvent): string {
  const parts: string[] = []
  const dataVersion = event.meta?.data_version
  if (typeof dataVersion === 'string' && dataVersion) parts.push(`数据版本 ${dataVersion}`)
  const model = event.meta?.model
  if (typeof model === 'string' && model) parts.push(`模型 ${model}`)
  const overBudget = event.meta?.over_budget
  if (typeof overBudget === 'number') parts.push(`超预算 ${overBudget} 元`)
  return parts.join(' · ')
}
</script>

<style scoped>
.trace-card {
  margin-top: 20px;
}

.trace-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  color: #333;
}

.trace-ms {
  color: #8c8c8c;
  font-size: 13px;
}

.trace-error {
  margin-top: 6px;
  color: #cf1322;
  font-size: 13px;
  word-break: break-word;
}

.trace-meta {
  margin-top: 4px;
  color: #8c8c8c;
  font-size: 12px;
}
</style>
