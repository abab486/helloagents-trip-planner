<template>
  <a-card id="budget" title="💰 预算明细" :bordered="false" class="budget-card">
    <div class="budget-total-row">
      <div>
        <div class="total-label">预估总费用</div>
        <div class="total-value">¥{{ budget.total }}</div>
      </div>
      <div class="budget-status">
        <template v-if="budget.budget_limit">
          <a-tag :color="budget.over_budget > 0 ? 'red' : 'green'">
            {{ budget.over_budget > 0 ? `超出 ¥${budget.over_budget}` : `结余 ¥${remaining}` }}
          </a-tag>
          <div class="limit-text">预算上限 ¥{{ budget.budget_limit }}</div>
        </template>
        <a-tag v-else color="blue">未设置上限</a-tag>
      </div>
    </div>

    <div class="category-grid">
      <div v-for="item in categoryTotals" :key="item.category" class="category-item">
        <div class="category-label">{{ item.label }}</div>
        <div class="category-value">¥{{ item.amount }}</div>
      </div>
    </div>

    <a-divider orientation="left">费用来源</a-divider>
    <div class="budget-lines">
      <div v-for="(line, index) in budget.lines" :key="`${line.category}-${line.ref_id}-${index}`" class="budget-line">
        <div class="line-main">
          <span class="line-name">{{ line.name }}</span>
          <a-tag :color="categoryColor(line.category)">{{ categoryLabel(line.category) }}</a-tag>
          <a-tag :color="sourceColor(line.source)">{{ sourceLabel(line.source) }}</a-tag>
        </div>
        <div class="line-side">
          <span class="line-amount">¥{{ line.amount }}</span>
          <span v-if="line.detail" class="line-detail">{{ line.detail }}</span>
        </div>
      </div>
    </div>

    <p class="budget-note">
      金额由代码按价格库/默认值计算，明细合计 = 总额；LLM 不参与算钱。
    </p>
  </a-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { BudgetCategory, BudgetReport } from '@/types'

const props = defineProps<{
  budget: BudgetReport
}>()

const remaining = computed(() => {
  if (!props.budget.budget_limit) return 0
  return Math.max(props.budget.budget_limit - props.budget.total, 0)
})

const categoryTotals = computed(() => {
  const categories: Array<{ category: BudgetCategory; label: string }> = [
    { category: 'attraction', label: '景点门票' },
    { category: 'hotel', label: '酒店住宿' },
    { category: 'meal', label: '餐饮' },
    { category: 'transport', label: '交通' }
  ]
  return categories.map((item) => ({
    ...item,
    amount: props.budget.lines
      .filter((line) => line.category === item.category)
      .reduce((sum, line) => sum + line.amount, 0)
  }))
})

function categoryLabel(category: BudgetCategory): string {
  return {
    attraction: '门票',
    hotel: '酒店',
    meal: '餐饮',
    transport: '交通'
  }[category] || category
}

function categoryColor(category: BudgetCategory): string {
  return {
    attraction: 'blue',
    hotel: 'purple',
    meal: 'orange',
    transport: 'cyan'
  }[category] || 'default'
}

function sourceLabel(source: string): string {
  return {
    csv: '价格库/CSV',
    db: '价格库',
    alias: '别名命中',
    fuzzy: '模糊匹配',
    default: '默认价',
    plan: '模型估值',
    tier: '档位均价'
  }[source] || source
}

function sourceColor(source: string): string {
  if (source === 'csv' || source === 'db' || source === 'alias' || source === 'fuzzy') return 'green'
  if (source === 'default' || source === 'plan') return 'orange'
  return 'default'
}
</script>

<style scoped>
.budget-card {
  height: fit-content;
}

.budget-total-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 18px;
  border-radius: 12px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
}

.total-label {
  font-size: 13px;
  opacity: 0.85;
}

.total-value {
  font-size: 32px;
  font-weight: 700;
  line-height: 1.2;
}

.budget-status {
  text-align: right;
}

.limit-text {
  margin-top: 6px;
  font-size: 12px;
  opacity: 0.85;
}

.category-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-top: 16px;
}

.category-item {
  padding: 12px;
  border: 1px solid #e8e8e8;
  border-radius: 10px;
  text-align: center;
}

.category-label {
  color: #8c8c8c;
  font-size: 12px;
}

.category-value {
  margin-top: 4px;
  color: #1890ff;
  font-size: 18px;
  font-weight: 600;
}

.budget-lines {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 360px;
  overflow-y: auto;
}

.budget-line {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 4px;
  border-bottom: 1px dashed #f0f0f0;
}

.line-main {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.line-name {
  color: #333;
  font-size: 13px;
}

.line-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  flex-shrink: 0;
}

.line-amount {
  color: #333;
  font-weight: 600;
}

.line-detail {
  color: #bfbfbf;
  font-size: 11px;
}

.budget-note {
  margin: 12px 0 0;
  color: #8c8c8c;
  font-size: 12px;
}

@media (max-width: 768px) {
  .category-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .budget-line {
    flex-direction: column;
  }

  .line-side {
    align-items: flex-start;
  }
}
</style>
