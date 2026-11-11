<template>
  <div class="home-container">
    <div class="bg-decoration">
      <div class="circle circle-1"></div>
      <div class="circle circle-2"></div>
      <div class="circle circle-3"></div>
    </div>

    <div class="page-header">
      <div class="badge">镇江 · 单城市深度版</div>
      <h1 class="page-title">镇江旅行助手</h1>
      <p class="page-subtitle">
        确定性 DAG 编排 · 只做镇江 · 每一笔预算都能解释
      </p>
      <div class="theme-chips">
        <span>三山一渡</span>
        <span>醋都寻味</span>
        <span>诗词镇江</span>
      </div>
    </div>

    <a-card class="form-card" :bordered="false">
      <a-form :model="formData" layout="vertical" @finish="handleSubmit">
        <div class="form-section">
          <div class="section-header">
            <span class="section-icon">📍</span>
            <span class="section-title">目的地与日期</span>
          </div>

          <a-row :gutter="24">
            <a-col :xs="24" :md="8">
              <a-form-item label="目的地" name="city">
                <a-input value="镇江" disabled size="large" class="custom-input">
                  <template #prefix><span class="input-prefix">🏙️</span></template>
                </a-input>
                <div class="field-hint">当前版本只支持镇江，先把一个城市做深。</div>
              </a-form-item>
            </a-col>
            <a-col :xs="12" :md="6">
              <a-form-item
                label="开始日期"
                name="start_date"
                :rules="[{ required: true, message: '请选择开始日期' }]"
              >
                <a-date-picker
                  v-model:value="formData.start_date"
                  size="large"
                  style="width: 100%"
                  placeholder="选择日期"
                />
              </a-form-item>
            </a-col>
            <a-col :xs="12" :md="6">
              <a-form-item
                label="结束日期"
                name="end_date"
                :rules="[{ required: true, message: '请选择结束日期' }]"
              >
                <a-date-picker
                  v-model:value="formData.end_date"
                  size="large"
                  style="width: 100%"
                  placeholder="选择日期"
                />
              </a-form-item>
            </a-col>
            <a-col :xs="24" :md="4">
              <a-form-item label="旅行天数">
                <div class="days-display">
                  <span class="days-value">{{ formData.travel_days }}</span>
                  <span class="days-unit">天</span>
                </div>
              </a-form-item>
            </a-col>
          </a-row>
        </div>

        <div class="form-section">
          <div class="section-header">
            <span class="section-icon">⚙️</span>
            <span class="section-title">出行偏好</span>
          </div>

          <a-row :gutter="24">
            <a-col :xs="24" :md="6">
              <a-form-item label="交通方式">
                <a-select v-model:value="formData.transportation" size="large">
                  <a-select-option value="公共交通">🚇 公共交通</a-select-option>
                  <a-select-option value="打车">🚕 打车</a-select-option>
                  <a-select-option value="自驾">🚗 自驾</a-select-option>
                  <a-select-option value="步行">🚶 步行</a-select-option>
                  <a-select-option value="混合">🔀 混合</a-select-option>
                </a-select>
              </a-form-item>
            </a-col>
            <a-col :xs="24" :md="6">
              <a-form-item label="住宿偏好">
                <a-select v-model:value="formData.accommodation" size="large">
                  <a-select-option value="经济型酒店">💰 经济型酒店</a-select-option>
                  <a-select-option value="舒适型酒店">🏨 舒适型酒店</a-select-option>
                  <a-select-option value="豪华酒店">⭐ 豪华酒店</a-select-option>
                  <a-select-option value="民宿">🏡 民宿</a-select-option>
                </a-select>
              </a-form-item>
            </a-col>
            <a-col :xs="24" :md="6">
              <a-form-item label="同行人">
                <a-select v-model:value="formData.party" size="large">
                  <a-select-option value="solo">🧍 一个人</a-select-option>
                  <a-select-option value="couple">💑 情侣/朋友</a-select-option>
                  <a-select-option value="family">👨‍👩‍👧 带孩子</a-select-option>
                  <a-select-option value="elderly">👵 带父母</a-select-option>
                </a-select>
              </a-form-item>
            </a-col>
            <a-col :xs="24" :md="6">
              <a-form-item label="行程节奏">
                <a-select v-model:value="formData.pace" size="large">
                  <a-select-option value="relaxed">☕ 轻松</a-select-option>
                  <a-select-option value="normal">🚶 适中</a-select-option>
                  <a-select-option value="packed">⚡ 紧凑</a-select-option>
                </a-select>
              </a-form-item>
            </a-col>
          </a-row>

          <a-form-item label="旅行主题（可多选）">
            <a-checkbox-group v-model:value="formData.preferences" class="preference-group">
              <a-checkbox value="历史文化">🏛️ 历史文化</a-checkbox>
              <a-checkbox value="美食">🍜 美食</a-checkbox>
              <a-checkbox value="自然风光">🏞️ 自然风光</a-checkbox>
              <a-checkbox value="亲子">🧒 亲子</a-checkbox>
              <a-checkbox value="摄影">📷 摄影</a-checkbox>
              <a-checkbox value="宗教">🛕 宗教</a-checkbox>
              <a-checkbox value="休闲">☕ 休闲</a-checkbox>
            </a-checkbox-group>
          </a-form-item>
        </div>

        <div class="form-section">
          <div class="section-header">
            <span class="section-icon">💰</span>
            <span class="section-title">预算与额外要求</span>
          </div>

          <a-row :gutter="24">
            <a-col :xs="24" :md="8">
              <a-form-item label="预算上限（元，可选）">
                <a-input-number
                  v-model:value="formData.budget_limit"
                  :min="0"
                  :step="100"
                  size="large"
                  style="width: 100%"
                  placeholder="例如 800"
                />
              </a-form-item>
            </a-col>
            <a-col :xs="24" :md="16">
              <a-form-item label="额外要求">
                <a-textarea
                  v-model:value="formData.free_text_input"
                  :rows="2"
                  size="large"
                  placeholder="例如：带父母，少爬坡；想吃锅盖面和肴肉；雨天优先室内"
                />
              </a-form-item>
            </a-col>
          </a-row>
        </div>

        <a-form-item>
          <a-button
            type="primary"
            html-type="submit"
            :loading="loading"
            size="large"
            block
            class="submit-button"
          >
            <template v-if="!loading">
              <span class="button-icon">🧭</span>
              <span>生成我的镇江行程</span>
            </template>
            <template v-else>
              <span>正在生成…</span>
            </template>
          </a-button>
        </a-form-item>

        <a-form-item v-if="loading">
          <div class="loading-container">
            <a-spin size="large" />
            <p class="loading-status">{{ loadingStatus }}</p>
            <p class="loading-hint">
              正在加载镇江数据 → Planner 选点 → 校验约束 → 代码算预算。预计 10–20 秒。
            </p>
          </div>
        </a-form-item>
      </a-form>
    </a-card>

    <p class="footer-note">
      价格与开放时间为参考值，出行前请以景区当日公示为准。本工具不提供实时票务/库存。
    </p>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { generateTripPlan } from '@/services/api'
import type { Party, Pace, TripFormData } from '@/types'
import type { Dayjs } from 'dayjs'

type TripFormState = Omit<TripFormData, 'start_date' | 'end_date'> & {
  start_date: Dayjs | null
  end_date: Dayjs | null
}

const router = useRouter()
const loading = ref(false)
const loadingStatus = ref('')
let timer: number | undefined

const formData = reactive<TripFormState>({
  city: '镇江',
  start_date: null,
  end_date: null,
  travel_days: 1,
  transportation: '公共交通',
  accommodation: '经济型酒店',
  preferences: ['历史文化'],
  free_text_input: '',
  budget_limit: 800,
  party: 'solo',
  pace: 'normal',
  must_see_ids: []
})

watch(
  [() => formData.start_date, () => formData.end_date],
  ([start, end]) => {
    if (!start || !end) return
    if (end.isBefore(start, 'day')) {
      message.warning('结束日期不能早于开始日期')
      formData.end_date = null
      return
    }
    const days = end.diff(start, 'day') + 1
    if (days > 7) {
      message.warning('当前版本最多规划 7 天，建议先试 1–3 天')
      formData.end_date = null
      return
    }
    formData.travel_days = days
  }
)

function idempotencyKey(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

function startLoadingClock() {
  const startedAt = Date.now()
  loadingStatus.value = '正在加载镇江数据…'
  timer = window.setInterval(() => {
    const elapsed = Math.floor((Date.now() - startedAt) / 1000)
    if (elapsed < 5) {
      loadingStatus.value = `正在加载镇江数据… 已用时 ${elapsed}s`
    } else if (elapsed < 12) {
      loadingStatus.value = `Planner 正在选择景点与酒店… 已用时 ${elapsed}s`
    } else if (elapsed < 20) {
      loadingStatus.value = `正在校验约束并计算预算… 已用时 ${elapsed}s`
    } else {
      loadingStatus.value = `正在整理行程与 Trace… 已用时 ${elapsed}s`
    }
  }, 1000)
}

function stopLoadingClock() {
  if (timer) {
    window.clearInterval(timer)
    timer = undefined
  }
}

async function handleSubmit() {
  if (!formData.start_date || !formData.end_date) {
    message.error('请选择日期')
    return
  }

  loading.value = true
  startLoadingClock()

  try {
    const payload: TripFormData = {
      city: '镇江',
      start_date: formData.start_date.format('YYYY-MM-DD'),
      end_date: formData.end_date.format('YYYY-MM-DD'),
      travel_days: formData.travel_days,
      transportation: formData.transportation,
      accommodation: formData.accommodation,
      preferences: formData.preferences,
      free_text_input: formData.free_text_input,
      budget_limit: formData.budget_limit ?? null,
      party: formData.party as Party,
      pace: formData.pace as Pace,
      must_see_ids: formData.must_see_ids ?? []
    }

    const response = await generateTripPlan(payload, idempotencyKey())
    if (!response.success || !response.data) {
      throw new Error(response.message || '生成失败')
    }

    sessionStorage.setItem('tripResponse', JSON.stringify(response))
    message.success('镇江行程生成成功')
    router.push('/result')
  } catch (error: any) {
    message.error(error?.message || '生成失败，请稍后重试')
  } finally {
    stopLoadingClock()
    loading.value = false
    loadingStatus.value = ''
  }
}

onBeforeUnmount(stopLoadingClock)
</script>

<style scoped>
.home-container {
  min-height: 100vh;
  padding: 48px 20px 64px;
  background:
    radial-gradient(circle at 10% 10%, rgba(255, 255, 255, 0.18), transparent 32%),
    linear-gradient(135deg, #667eea 0%, #764ba2 55%, #5b3f8c 100%);
  position: relative;
  overflow: hidden;
}

.bg-decoration {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

.circle {
  position: absolute;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.08);
  animation: float 20s infinite ease-in-out;
}

.circle-1 {
  width: 320px;
  height: 320px;
  top: -120px;
  left: -100px;
}

.circle-2 {
  width: 220px;
  height: 220px;
  top: 45%;
  right: -70px;
  animation-delay: 5s;
}

.circle-3 {
  width: 160px;
  height: 160px;
  bottom: -60px;
  left: 30%;
  animation-delay: 10s;
}

@keyframes float {
  0%, 100% { transform: translateY(0) rotate(0deg); }
  50% { transform: translateY(-24px) rotate(160deg); }
}

.page-header {
  position: relative;
  z-index: 1;
  max-width: 1100px;
  margin: 0 auto 28px;
  text-align: center;
  color: #fff;
  animation: fadeInDown 0.7s ease-out;
}

.badge {
  display: inline-block;
  padding: 6px 14px;
  border: 1px solid rgba(255, 255, 255, 0.35);
  border-radius: 999px;
  color: rgba(255, 255, 255, 0.9);
  font-size: 13px;
  letter-spacing: 1px;
}

.page-title {
  margin: 16px 0 8px;
  font-size: 48px;
  font-weight: 800;
  letter-spacing: 2px;
  text-shadow: 0 4px 18px rgba(0, 0, 0, 0.25);
}

.page-subtitle {
  margin: 0;
  font-size: 17px;
  color: rgba(255, 255, 255, 0.88);
}

.theme-chips {
  display: flex;
  justify-content: center;
  gap: 10px;
  margin-top: 16px;
  flex-wrap: wrap;
}

.theme-chips span {
  padding: 5px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.14);
  color: #fff;
  font-size: 13px;
}

.form-card {
  position: relative;
  z-index: 1;
  max-width: 1100px;
  margin: 0 auto;
  border-radius: 22px;
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.32);
  background: rgba(255, 255, 255, 0.98) !important;
  animation: fadeInUp 0.7s ease-out;
}

.form-section {
  margin-bottom: 24px;
  padding: 20px;
  border: 1px solid #ececf4;
  border-radius: 16px;
  background: linear-gradient(135deg, #f8f9ff 0%, #ffffff 100%);
}

.section-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 18px;
  padding-bottom: 10px;
  border-bottom: 2px solid #667eea;
}

.section-icon {
  font-size: 20px;
}

.section-title {
  color: #333;
  font-size: 17px;
  font-weight: 600;
}

.field-hint {
  margin-top: 6px;
  color: #999;
  font-size: 12px;
}

.input-prefix {
  color: #667eea;
}

.days-display {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 40px;
  border-radius: 12px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
}

.days-value {
  font-size: 24px;
  font-weight: 700;
  margin-right: 4px;
}

.days-unit {
  font-size: 13px;
}

.preference-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.preference-group :deep(.ant-checkbox-wrapper) {
  margin: 0 !important;
  padding: 8px 14px;
  border: 2px solid #e8e8e8;
  border-radius: 999px;
  background: #fff;
  transition: all 0.2s ease;
}

.preference-group :deep(.ant-checkbox-wrapper:hover) {
  border-color: #667eea;
}

.preference-group :deep(.ant-checkbox-wrapper-checked) {
  border-color: #667eea;
  background: #f0f2ff;
}

.submit-button {
  height: 54px;
  border: none;
  border-radius: 999px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  box-shadow: 0 10px 26px rgba(102, 126, 234, 0.35);
  font-size: 17px;
  font-weight: 600;
}

.button-icon {
  margin-right: 8px;
}

.loading-container {
  padding: 26px;
  border: 2px dashed #667eea;
  border-radius: 16px;
  text-align: center;
  background: linear-gradient(135deg, #f8f9ff 0%, #ffffff 100%);
}

.loading-status {
  margin: 14px 0 6px;
  color: #4a4a8a;
  font-size: 16px;
  font-weight: 600;
}

.loading-hint {
  margin: 0;
  color: #8c8c8c;
  font-size: 12px;
}

.footer-note {
  position: relative;
  z-index: 1;
  max-width: 1100px;
  margin: 18px auto 0;
  color: rgba(255, 255, 255, 0.72);
  font-size: 12px;
  text-align: center;
}

@keyframes fadeInDown {
  from { opacity: 0; transform: translateY(-18px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(18px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (max-width: 768px) {
  .home-container {
    padding: 28px 12px 44px;
  }

  .page-title {
    font-size: 34px;
  }

  .page-subtitle {
    font-size: 14px;
  }

  .form-card :deep(.ant-card-body) {
    padding: 14px;
  }

  .form-section {
    padding: 14px;
  }
}
</style>
