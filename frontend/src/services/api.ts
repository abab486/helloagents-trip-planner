import axios from 'axios'
import type { RecalculatePlan, TripFormData, TripPlanResponse } from '@/types'

const configuredBase = import.meta.env.VITE_API_BASE_URL
export const API_BASE_URL =
  configuredBase === '/' ? '' : configuredBase || 'http://localhost:8000'

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 180000,
  headers: {
    'Content-Type': 'application/json'
  }
})

function errorMessage(error: any): string {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  if (Array.isArray(detail)) {
    return detail.map((item: any) => item?.msg || JSON.stringify(item)).join('；')
  }
  return error?.message || '请求失败'
}

export async function generateTripPlan(
  formData: TripFormData,
  idempotencyKey?: string
): Promise<TripPlanResponse> {
  try {
    const response = await apiClient.post<TripPlanResponse>('/api/v1/trips', formData, {
      headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined
    })
    return response.data
  } catch (error: any) {
    throw new Error(errorMessage(error))
  }
}

export async function recalculateTrip(
  tripId: string,
  plan: RecalculatePlan
): Promise<TripPlanResponse> {
  try {
    const response = await apiClient.post<TripPlanResponse>(
      `/api/v1/trips/${encodeURIComponent(tripId)}/recalculate`,
      { plan }
    )
    return response.data
  } catch (error: any) {
    throw new Error(errorMessage(error))
  }
}

export async function healthCheck(): Promise<any> {
  try {
    const response = await apiClient.get('/health')
    return response.data
  } catch (error: any) {
    throw new Error(errorMessage(error))
  }
}

export default apiClient
