<template>
  <div class="result-container">
    <div class="page-header">
      <a-button class="back-button" size="large" @click="goBack">← 返回首页</a-button>
      <a-space size="middle" wrap>
        <a-tag v-if="meta?.cached" color="blue">缓存命中</a-tag>
        <a-tag v-if="tripData?.degraded" color="orange">降级结果</a-tag>

        <template v-if="!editMode">
          <a-button @click="toggleEdit">✏️ 编辑行程</a-button>
          <a-dropdown>
            <template #overlay>
              <a-menu>
                <a-menu-item key="image" @click="exportAsImage">📷 导出图片</a-menu-item>
                <a-menu-item key="pdf" @click="exportAsPDF">📄 导出 PDF</a-menu-item>
              </a-menu>
            </template>
            <a-button>📥 导出行程 <DownOutlined /></a-button>
          </a-dropdown>
        </template>
        <template v-else>
          <a-button type="primary" :loading="recalculating" @click="saveAndRecalculate">
            💾 保存并重算
          </a-button>
          <a-button @click="cancelEdit">取消</a-button>
        </template>
      </a-space>
    </div>

    <div v-if="tripData" class="content-wrapper">
      <div class="side-nav">
        <a-affix :offset-top="24">
          <a-menu mode="inline" :selected-keys="[activeSection]" @click="scrollToSection">
            <a-menu-item key="overview">📋 行程概览</a-menu-item>
            <a-menu-item key="budget">💰 预算明细</a-menu-item>
            <a-menu-item key="map">📍 景点地图</a-menu-item>
            <a-sub-menu key="days" title="📅 每日行程">
              <a-menu-item v-for="(day, index) in tripData.days" :key="`day-${index}`">
                第{{ day.day_index + 1 }}天
              </a-menu-item>
            </a-sub-menu>
            <a-menu-item v-if="tripData.trace.length" key="trace">🧭 执行轨迹</a-menu-item>
            <a-menu-item v-if="tripData.weather.length" key="weather">🌤️ 天气参考</a-menu-item>
          </a-menu>
        </a-affix>
      </div>

      <div class="main-content">
        <a-alert
          v-if="tripData.degraded"
          type="warning"
          show-icon
          class="top-alert"
          message="部分数据降级"
          description="某些节点的数据不可用，结果已标记为 degraded；请核对后再使用。"
        />
        <a-alert
          v-if="blockingIssues.length"
          type="error"
          show-icon
          class="top-alert"
          message="行程存在校验问题"
          :description="issueText(blockingIssues)"
        />
        <a-alert
          v-else-if="warningIssues.length"
          type="info"
          show-icon
          class="top-alert"
          message="提示"
          :description="issueText(warningIssues)"
        />

        <div class="top-info-section">
          <div class="left-info">
            <a-card id="overview" :title="`${tripData.request.city}旅行计划`" :bordered="false" class="overview-card">
              <div class="overview-list">
                <div class="overview-row">
                  <span class="overview-label">📅 日期</span>
                  <span>{{ tripData.request.start_date }} 至 {{ tripData.request.end_date }}（{{ tripData.request.travel_days }} 天）</span>
                </div>
                <div class="overview-row">
                  <span class="overview-label">🎯 主题</span>
                  <span>{{ preferenceText }}</span>
                </div>
                <div class="overview-row">
                  <span class="overview-label">🚇 交通</span>
                  <span>{{ tripData.request.transportation }}</span>
                </div>
                <div class="overview-row">
                  <span class="overview-label">🏨 住宿</span>
                  <span>{{ tripData.request.accommodation }}</span>
                </div>
                <div v-if="meta" class="overview-row meta-row">
                  <span class="overview-label">🧾 记录</span>
                  <span class="mono">{{ meta.trip_id }} · {{ meta.request_id }}</span>
                </div>
                <div v-if="tripData.notes.length" class="overview-row">
                  <span class="overview-label">💡 说明</span>
                  <span>{{ tripData.notes.join('；') }}</span>
                </div>
              </div>
            </a-card>

            <BudgetPanel :budget="tripData.budget" />
          </div>

          <div class="right-map">
            <a-card id="map" title="📍 景点地图" :bordered="false" class="map-card">
              <div id="amap-container"></div>
              <p class="map-note">按天连线只表示游览顺序，不是实时导航路线。</p>
            </a-card>
          </div>
        </div>

        <TraceTimeline :trace="tripData.trace" />

        <a-card v-if="tripData.weather.length" id="weather" title="🌤️ 天气参考" :bordered="false" class="weather-section">
          <a-row :gutter="[12, 12]">
            <a-col v-for="weather in tripData.weather" :key="weather.date" :xs="24" :md="8">
              <div class="weather-card">
                <div class="weather-date">{{ weather.date }}</div>
                <div class="weather-main">
                  <span class="weather-icon">{{ weather.day_weather.includes('雨') ? '🌧️' : '☀️' }}</span>
                  <div>
                    <div class="weather-day">{{ weather.day_weather }} {{ weather.day_temp }}°C</div>
                    <div class="weather-night">夜间 {{ weather.night_weather }} {{ weather.night_temp }}°C</div>
                  </div>
                </div>
                <div class="weather-rain">降水概率 {{ weather.precipitation_prob }}% · {{ weather.source }}</div>
              </div>
            </a-col>
          </a-row>
        </a-card>

        <a-card title="📅 每日行程" :bordered="false" class="days-card">
          <a-collapse v-model:activeKey="activeDays" accordion>
            <a-collapse-panel
              v-for="(day, index) in tripData.days"
              :key="index"
              :id="`day-${index}`"
            >
              <template #header>
                <div class="day-header">
                  <div>
                    <span class="day-title">第{{ day.day_index + 1 }}天</span>
                    <span class="day-date">{{ day.date }}</span>
                  </div>
                  <div class="day-header-right">
                    <a-tag v-if="day.theme" color="purple">{{ day.theme }}</a-tag>
                    <a-tag color="blue">{{ day.transport_mode }}</a-tag>
                  </div>
                </div>
              </template>

              <a-list
                :data-source="day.attractions"
                :grid="{ gutter: 16, column: 2 }"
                class="attraction-list"
              >
                <template #renderItem="{ item, index: attrIndex }">
                  <a-list-item>
                    <a-card :title="item.name" size="small" class="attraction-card">
                      <template #extra v-if="editMode">
                        <a-button
                          danger
                          size="small"
                          :disabled="day.attractions.length <= 1"
                          @click="deleteAttraction(day.day_index, attrIndex)"
                        >
                          删除
                        </a-button>
                      </template>

                      <div class="attraction-image-wrapper">
                        <img
                          :src="getAttractionImage(item.name, attrIndex)"
                          :alt="item.name"
                          class="attraction-image"
                          @error="handleImageError"
                        />
                        <div class="attraction-index">{{ attrIndex + 1 }}</div>
                        <div v-if="item.must_see" class="must-see-badge">必去</div>
                      </div>

                      <div class="attraction-tags">
                        <a-tag color="blue">{{ item.area }}</a-tag>
                        <a-tag :color="item.ticket_price > 0 ? 'orange' : 'green'">
                          {{ item.ticket_price > 0 ? `¥${item.ticket_price}` : '免费' }}
                        </a-tag>
                        <a-tag color="cyan">{{ item.duration_min }} 分钟</a-tag>
                        <a-tag v-if="item.indoor" color="purple">室内</a-tag>
                        <a-tag color="default">步行强度 {{ item.walking_level }}/3</a-tag>
                      </div>

                      <p class="attraction-desc">{{ item.description || '暂无描述' }}</p>
                    </a-card>
                  </a-list-item>
                </template>
              </a-list>

              <div v-if="day.hotel" class="hotel-block">
                <div class="block-title">🏨 住宿建议</div>
                <div class="hotel-card">
                  <div>
                    <div class="hotel-name">{{ day.hotel.name }}</div>
                    <div class="hotel-meta">{{ day.hotel.tier }} · {{ day.hotel.area }}</div>
                  </div>
                  <div class="hotel-price">¥{{ day.hotel.price_per_night }}<span>/晚</span></div>
                </div>
              </div>

              <div class="meal-block">
                <div class="block-title">🍽️ 餐饮安排</div>
                <div class="meal-grid">
                  <div v-for="meal in day.meals" :key="`${meal.type}-${meal.restaurant_id}`" class="meal-item">
                    <div class="meal-type">{{ mealLabel(meal.type) }}</div>
                    <div class="meal-name">{{ meal.name }}</div>
                    <div class="meal-meta">{{ meal.area }} · 约 ¥{{ meal.avg_price }}</div>
                  </div>
                </div>
              </div>
            </a-collapse-panel>
          </a-collapse>
        </a-card>
      </div>
    </div>

    <a-empty v-else description="没有找到行程数据">
      <template #description>
        <span class="empty-text">暂无行程，请先回首页生成一份镇江计划</span>
      </template>
      <a-button type="primary" @click="goBack">返回首页</a-button>
    </a-empty>

    <a-back-top :visibility-height="300">
      <div class="back-top">↑</div>
    </a-back-top>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { DownOutlined } from '@ant-design/icons-vue'
import AMapLoader from '@amap/amap-jsapi-loader'
import html2canvas from 'html2canvas'
import jsPDF from 'jspdf'
import BudgetPanel from '@/components/BudgetPanel.vue'
import TraceTimeline from '@/components/TraceTimeline.vue'
import { API_BASE_URL, recalculateTrip } from '@/services/api'
import type {
  RecalculatePlan,
  TripPlanResponse,
  TripResult,
  ValidationIssue
} from '@/types'

interface TripMeta {
  trip_id: string
  request_id: string
  cached: boolean
  message: string
}

const router = useRouter()
const tripData = ref<TripResult | null>(null)
const meta = ref<TripMeta | null>(null)
const editMode = ref(false)
const recalculating = ref(false)
const originalPlan = ref<TripResult | null>(null)
const activeSection = ref('overview')
const activeDays = ref<(string | number)[]>([0])
const photos = ref<Record<string, string>>({})
let map: any = null

const preferenceText = computed(() => {
  const preferences = tripData.value?.request.preferences ?? []
  return preferences.length ? preferences.join(' / ') : '综合'
})

const blockingIssues = computed<ValidationIssue[]>(() =>
  (tripData.value?.validation.issues ?? []).filter((issue) => issue.severity === 'blocking')
)

const warningIssues = computed<ValidationIssue[]>(() =>
  (tripData.value?.validation.issues ?? []).filter((issue) => issue.severity === 'warning')
)

function issueText(issues: ValidationIssue[]): string {
  return issues.slice(0, 3).map((issue) => issue.message).join('；')
}

onMounted(async () => {
  const raw = sessionStorage.getItem('tripResponse')
  if (!raw) return
  try {
    const response = JSON.parse(raw) as TripPlanResponse
    if (!response.data) return
    tripData.value = response.data
    meta.value = {
      trip_id: response.trip_id,
      request_id: response.request_id,
      cached: response.cached,
      message: response.message
    }
    await loadPhotos()
    await nextTick()
    await initMap()
  } catch (error) {
    console.error('读取行程缓存失败', error)
    message.error('读取行程缓存失败，请回首页重新生成')
  }
})

onBeforeUnmount(() => {
  if (map) {
    map.destroy()
    map = null
  }
})

function goBack() {
  router.push('/')
}

function scrollToSection({ key }: { key: string }) {
  activeSection.value = key
  const element = document.getElementById(key)
  if (element) element.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function toggleEdit() {
  if (!tripData.value) return
  editMode.value = true
  originalPlan.value = JSON.parse(JSON.stringify(tripData.value))
  message.info('编辑模式：可以删除景点，保存时会重新校验并重算预算')
}

function cancelEdit() {
  if (originalPlan.value) {
    tripData.value = JSON.parse(JSON.stringify(originalPlan.value))
  }
  editMode.value = false
  message.info('已取消编辑')
}

function deleteAttraction(dayIndex: number, attrIndex: number) {
  if (!tripData.value) return
  const day = tripData.value.days[dayIndex]
  if (!day) return
  if (day.attractions.length <= 1) {
    message.warning('每天至少保留一个景点')
    return
  }
  day.attractions.splice(attrIndex, 1)
}

function buildRecalculatePlan(): RecalculatePlan {
  if (!tripData.value) throw new Error('缺少行程数据')
  return {
    days: tripData.value.days.map((day) => {
      if (!day.hotel?.id) throw new Error(`第 ${day.day_index + 1} 天缺少酒店，无法重算`)
      return {
        date: day.date,
        attraction_ids: day.attractions.map((item) => item.id),
        hotel_id: day.hotel.id,
        meals: day.meals.map((meal) => ({
          type: meal.type,
          restaurant_id: meal.restaurant_id
        })),
        transport_mode: day.transport_mode,
        theme: day.theme
      }
    }),
    notes: tripData.value.notes
  }
}

async function saveAndRecalculate() {
  if (!tripData.value || !meta.value) {
    message.error('缺少行程记录，请回首页重新生成')
    return
  }

  recalculating.value = true
  try {
    const response = await recalculateTrip(meta.value.trip_id, buildRecalculatePlan())
    if (!response.success || !response.data) {
      throw new Error(response.message || '重算失败')
    }
    tripData.value = response.data
    meta.value = {
      trip_id: response.trip_id,
      request_id: response.request_id,
      cached: response.cached,
      message: response.message
    }
    sessionStorage.setItem('tripResponse', JSON.stringify(response))
    editMode.value = false
    originalPlan.value = null
    await nextTick()
    await initMap()
    message.success(`预算已重算：¥${response.data.budget.total}`)
  } catch (error: any) {
    message.error(error?.message || '重算失败')
  } finally {
    recalculating.value = false
  }
}

function mealLabel(type: string): string {
  return {
    breakfast: '早餐',
    lunch: '午餐',
    dinner: '晚餐'
  }[type] || type
}

async function loadPhotos() {
  if (!tripData.value) return
  const names = Array.from(
    new Set(
      tripData.value.days.flatMap((day) => day.attractions.map((item) => item.name))
    )
  )
  await Promise.allSettled(
    names.map(async (name) => {
      try {
        const response = await fetch(
          `${API_BASE_URL}/api/poi/photo?name=${encodeURIComponent(name)}`
        )
        if (!response.ok) return
        const payload = await response.json()
        if (payload?.success && payload?.data?.photo_url) {
          photos.value[name] = payload.data.photo_url
        }
      } catch {
        // Photo is optional; the gradient placeholder is fine.
      }
    })
  )
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function getAttractionImage(name: string, index: number): string {
  if (photos.value[name]) return photos.value[name]

  const colors = [
    ['#667eea', '#764ba2'],
    ['#f093fb', '#f5576c'],
    ['#4facfe', '#00f2fe'],
    ['#43e97b', '#38f9d7'],
    ['#fa709a', '#fee140']
  ]
  const [start, end] = colors[index % colors.length]
  const safeName = escapeHtml(name)
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="480" height="300">
    <defs>
      <linearGradient id="g${index}" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="${start}" />
        <stop offset="100%" stop-color="${end}" />
      </linearGradient>
    </defs>
    <rect width="480" height="300" fill="url(#g${index})" />
    <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle"
      font-family="sans-serif" font-size="26" font-weight="700" fill="white">${safeName}</text>
  </svg>`
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`
}

function handleImageError(event: Event) {
  const image = event.target as HTMLImageElement
  image.src =
    'data:image/svg+xml;charset=UTF-8,' +
    encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg" width="480" height="300"><rect width="480" height="300" fill="#f0f0f0"/><text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" font-family="sans-serif" font-size="18" fill="#999">图片加载失败</text></svg>'
    )
}

async function initMap() {
  if (!tripData.value) return
  const key = import.meta.env.VITE_AMAP_WEB_JS_KEY
  if (!key) {
    message.warning('未配置 VITE_AMAP_WEB_JS_KEY，地图暂不可用')
    return
  }

  try {
    const AMap = await AMapLoader.load({
      key,
      version: '2.0',
      plugins: ['AMap.Marker', 'AMap.Polyline', 'AMap.InfoWindow']
    })

    if (map) map.destroy()
    const allAttractions = tripData.value.days.flatMap((day) =>
      day.attractions.map((attraction) => ({ ...attraction, day_index: day.day_index }))
    )
    const first = allAttractions[0]
    const center = first ? [first.lng, first.lat] : [119.44, 32.2]

    map = new AMap.Map('amap-container', {
      zoom: 12,
      center,
      viewMode: '3D'
    })

    const markers: any[] = []
    allAttractions.forEach((attraction, index) => {
      if (!attraction.lat || !attraction.lng) return
      const marker = new AMap.Marker({
        position: [attraction.lng, attraction.lat],
        title: attraction.name,
        label: {
          content: `<div class="amap-label">${index + 1}</div>`,
          offset: new AMap.Pixel(0, -28)
        }
      })
      const content = `
        <div class="amap-info">
          <h4>${escapeHtml(attraction.name)}</h4>
          <p>${escapeHtml(attraction.area)} · ¥${attraction.ticket_price} · ${attraction.duration_min} 分钟</p>
          <p>${escapeHtml(attraction.description || '')}</p>
          <p class="amap-info-day">第 ${attraction.day_index + 1} 天</p>
        </div>`
      const infoWindow = new AMap.InfoWindow({ content, offset: new AMap.Pixel(0, -30) })
      marker.on('click', () => infoWindow.open(map, marker.getPosition()))
      markers.push(marker)
    })
    map.add(markers)
    if (markers.length) map.setFitView(markers)

    tripData.value.days.forEach((day) => {
      const points = day.attractions
        .filter((item) => item.lat && item.lng)
        .map((item) => [item.lng, item.lat])
      if (points.length < 2) return
      const polyline = new AMap.Polyline({
        path: points,
        strokeColor: '#667eea',
        strokeWeight: 4,
        strokeOpacity: 0.8,
        showDir: true
      })
      map.add(polyline)
    })
  } catch (error) {
    console.error('地图加载失败', error)
    message.warning('地图加载失败，行程文字内容仍可正常使用')
  }
}

async function createExportCanvas(): Promise<HTMLCanvasElement> {
  const element = document.querySelector('.main-content') as HTMLElement | null
  if (!element) throw new Error('未找到内容区域')

  const container = document.createElement('div')
  container.style.width = `${element.offsetWidth}px`
  container.style.backgroundColor = '#f5f7fa'
  container.style.padding = '20px'
  container.innerHTML = element.innerHTML

  const mapCanvas = document.querySelector('#amap-container canvas') as HTMLCanvasElement | null
  if (mapCanvas) {
    try {
      const snapshot = mapCanvas.toDataURL('image/png')
      const target = container.querySelector('#amap-container')
      if (target) {
        target.innerHTML = `<img src="${snapshot}" style="width:100%;height:100%;object-fit:cover;" />`
      }
    } catch {
      // Tainted canvas is not fatal; export without the map.
    }
  }

  container.style.position = 'absolute'
  container.style.left = '-10000px'
  container.style.top = '0'
  document.body.appendChild(container)
  try {
    return await html2canvas(container, {
      backgroundColor: '#f5f7fa',
      scale: 2,
      logging: false,
      useCORS: true
    })
  } finally {
    document.body.removeChild(container)
  }
}

async function exportAsImage() {
  try {
    message.loading({ content: '正在生成图片…', key: 'export', duration: 0 })
    const canvas = await createExportCanvas()
    const link = document.createElement('a')
    link.download = `镇江行程_${Date.now()}.png`
    link.href = canvas.toDataURL('image/png')
    link.click()
    message.success({ content: '图片已导出', key: 'export' })
  } catch (error: any) {
    message.error({ content: `导出失败：${error?.message || error}`, key: 'export' })
  }
}

async function exportAsPDF() {
  try {
    message.loading({ content: '正在生成 PDF…', key: 'export', duration: 0 })
    const canvas = await createExportCanvas()
    const image = canvas.toDataURL('image/png')
    const pdf = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' })
    const pageWidth = 210
    const pageHeight = 297
    const imageHeight = (canvas.height * pageWidth) / canvas.width

    let heightLeft = imageHeight
    let position = 0
    pdf.addImage(image, 'PNG', 0, position, pageWidth, imageHeight)
    heightLeft -= pageHeight
    while (heightLeft > 0) {
      position = heightLeft - imageHeight
      pdf.addPage()
      pdf.addImage(image, 'PNG', 0, position, pageWidth, imageHeight)
      heightLeft -= pageHeight
    }
    pdf.save(`镇江行程_${Date.now()}.pdf`)
    message.success({ content: 'PDF 已导出', key: 'export' })
  } catch (error: any) {
    message.error({ content: `导出失败：${error?.message || error}`, key: 'export' })
  }
}
</script>

<style scoped>
.result-container {
  min-height: 100vh;
  padding: 28px 20px 60px;
  background: linear-gradient(135deg, #f4f6fb 0%, #dfe5f3 100%);
}

.page-header {
  max-width: 1400px;
  margin: 0 auto 22px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.back-button {
  border-radius: 10px;
  font-weight: 500;
}

.content-wrapper {
  max-width: 1400px;
  margin: 0 auto;
  display: flex;
  gap: 22px;
  align-items: flex-start;
}

.side-nav {
  width: 220px;
  flex-shrink: 0;
}

.side-nav :deep(.ant-menu) {
  border-radius: 14px;
  box-shadow: 0 6px 18px rgba(38, 50, 90, 0.08);
}

.side-nav :deep(.ant-menu-item) {
  margin: 4px 8px;
  border-radius: 8px;
}

.side-nav :deep(.ant-menu-item-selected) {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
}

.main-content {
  flex: 1;
  min-width: 0;
}

.top-alert {
  margin-bottom: 16px;
  border-radius: 12px;
}

.top-info-section {
  display: flex;
  gap: 18px;
  align-items: stretch;
}

.left-info {
  flex: 0 0 420px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.right-map {
  flex: 1;
  min-width: 0;
}

.overview-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.overview-row {
  display: flex;
  gap: 12px;
  color: #333;
  font-size: 14px;
  line-height: 1.6;
}

.overview-label {
  flex-shrink: 0;
  color: #8c8c8c;
  min-width: 62px;
}

.meta-row {
  padding-top: 8px;
  border-top: 1px dashed #eee;
}

.mono {
  color: #8c8c8c;
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
  word-break: break-all;
}

.map-card {
  height: 100%;
  min-height: 520px;
}

.map-card :deep(.ant-card-body) {
  height: calc(100% - 57px);
  padding: 0;
  display: flex;
  flex-direction: column;
}

#amap-container {
  flex: 1;
  min-height: 460px;
  width: 100%;
}

.map-note {
  margin: 0;
  padding: 8px 14px;
  color: #999;
  font-size: 12px;
  border-top: 1px solid #f0f0f0;
}

.attraction-list {
  margin-top: 8px;
}

.attraction-card {
  height: 100%;
  overflow: hidden;
}

.attraction-image-wrapper {
  position: relative;
  margin: -4px -4px 12px;
  overflow: hidden;
  border-radius: 10px;
}

.attraction-image {
  width: 100%;
  height: 180px;
  object-fit: cover;
  transition: transform 0.3s ease;
}

.attraction-card:hover .attraction-image {
  transform: scale(1.04);
}

.attraction-index {
  position: absolute;
  top: 10px;
  left: 10px;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: #fff;
  font-weight: 700;
}

.must-see-badge {
  position: absolute;
  top: 10px;
  right: 10px;
  padding: 3px 9px;
  border-radius: 999px;
  background: rgba(255, 77, 79, 0.92);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
}

.attraction-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}

.attraction-tags :deep(.ant-tag) {
  margin: 0;
}

.attraction-desc {
  margin: 0;
  color: #595959;
  font-size: 13px;
  line-height: 1.7;
}

.hotel-block,
.meal-block {
  margin-top: 18px;
}

.block-title {
  margin-bottom: 10px;
  color: #333;
  font-weight: 600;
}

.hotel-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
  padding: 14px 16px;
  border: 1px solid #dbe4ff;
  border-radius: 12px;
  background: linear-gradient(135deg, #f2f6ff 0%, #ffffff 100%);
}

.hotel-name {
  color: #1d39c4;
  font-weight: 600;
}

.hotel-meta {
  margin-top: 4px;
  color: #8c8c8c;
  font-size: 12px;
}

.hotel-price {
  color: #1d39c4;
  font-size: 22px;
  font-weight: 700;
}

.hotel-price span {
  font-size: 12px;
  font-weight: 400;
  color: #8c8c8c;
}

.meal-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}

.meal-item {
  padding: 12px;
  border: 1px solid #f0f0f0;
  border-radius: 10px;
  background: #fff;
}

.meal-type {
  color: #fa8c16;
  font-size: 12px;
  font-weight: 600;
}

.meal-name {
  margin-top: 4px;
  color: #333;
  font-size: 14px;
}

.meal-meta {
  margin-top: 4px;
  color: #999;
  font-size: 12px;
}

.weather-section {
  margin-top: 20px;
}

.weather-card {
  padding: 14px;
  border-radius: 12px;
  background: linear-gradient(135deg, #f0f9ff 0%, #e6f7ff 100%);
  border: 1px solid #d6ecff;
}

.weather-date {
  color: #00796b;
  font-weight: 600;
  text-align: center;
}

.weather-main {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
}

.weather-icon {
  font-size: 30px;
}

.weather-day {
  color: #005f56;
  font-weight: 600;
}

.weather-night {
  margin-top: 4px;
  color: #5c8f89;
  font-size: 12px;
}

.weather-rain {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed #b7e4e0;
  color: #5c8f89;
  font-size: 12px;
  text-align: center;
}

.day-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  width: 100%;
}

.day-title {
  margin-right: 10px;
  color: #333;
  font-size: 17px;
  font-weight: 600;
}

.day-date {
  color: #999;
  font-size: 13px;
}

.day-header-right {
  display: flex;
  gap: 6px;
}

.days-card {
  margin-top: 20px;
}

.empty-text {
  color: #999;
}

.back-top {
  width: 46px;
  height: 46px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: #fff;
  font-size: 22px;
  box-shadow: 0 6px 18px rgba(102, 126, 234, 0.4);
}

:deep(.ant-card) {
  border-radius: 14px;
  box-shadow: 0 6px 18px rgba(38, 50, 90, 0.06);
}

:deep(.ant-card-head) {
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: #fff;
  border-radius: 14px 14px 0 0;
}

:deep(.ant-card-head-title) {
  color: #fff;
}

:deep(.ant-card-head-title span) {
  color: #fff;
}

:deep(.ant-collapse) {
  border: none;
  background: transparent;
}

:deep(.ant-collapse-item) {
  margin-bottom: 14px;
  border: 1px solid #ececf4;
  border-radius: 12px;
  overflow: hidden;
}

:deep(.ant-collapse-header) {
  background: #fafbff;
  padding: 14px 18px !important;
}

:deep(.ant-collapse-content-box) {
  padding: 18px;
}

:deep(.amap-label) {
  padding: 3px 8px;
  border-radius: 4px;
  background: #667eea;
  color: #fff;
  font-size: 12px;
  font-weight: 600;
}

:deep(.amap-info h4) {
  margin: 0 0 8px;
}

:deep(.amap-info p) {
  margin: 4px 0;
  font-size: 12px;
}

:deep(.amap-info-day) {
  color: #667eea;
  font-weight: 600;
}

@media (max-width: 1100px) {
  .top-info-section {
    flex-direction: column;
  }

  .left-info {
    flex-basis: auto;
    width: 100%;
  }

  .map-card {
    min-height: 420px;
  }

  #amap-container {
    min-height: 360px;
  }
}

@media (max-width: 900px) {
  .content-wrapper {
    flex-direction: column;
  }

  .side-nav {
    display: none;
  }

  .main-content {
    width: 100%;
  }
}

@media (max-width: 768px) {
  .result-container {
    padding: 18px 10px 40px;
  }

  .attraction-list :deep(.ant-list-item) {
    width: 100% !important;
  }

  .meal-grid {
    grid-template-columns: 1fr;
  }

  .page-header {
    align-items: flex-start;
  }
}
</style>
