// API v1 types. Keep the frontend aligned with backend TripResult.

export type Party = 'solo' | 'couple' | 'family' | 'elderly'
export type Pace = 'relaxed' | 'normal' | 'packed'
export type MealType = 'breakfast' | 'lunch' | 'dinner'

export interface TripFormData {
  city: string
  start_date: string
  end_date: string
  travel_days: number
  transportation: string
  accommodation: string
  preferences: string[]
  free_text_input: string
  budget_limit?: number | null
  party: Party
  pace: Pace
  must_see_ids?: string[]
}

export interface AttractionView {
  id: string
  name: string
  area: string
  ticket_price: number
  duration_min: number
  description: string
  must_see: boolean
  indoor: boolean
  walking_level: number
  lat: number
  lng: number
}

export interface HotelView {
  id: string
  name: string
  tier: string
  area: string
  price_per_night: number
  lat: number
  lng: number
}

export interface MealView {
  type: MealType | string
  restaurant_id: string
  name: string
  avg_price: number
  area: string
}

export interface WeatherView {
  date: string
  day_weather: string
  night_weather: string
  day_temp: number
  night_temp: number
  precipitation_prob: number
  source: string
}

export interface DayView {
  date: string
  day_index: number
  theme: string
  transport_mode: string
  attractions: AttractionView[]
  hotel?: HotelView | null
  meals: MealView[]
}

export type BudgetCategory = 'attraction' | 'hotel' | 'meal' | 'transport'

export interface BudgetLine {
  category: BudgetCategory
  ref_id: string
  name: string
  amount: number
  source: string
  detail: string
}

export interface BudgetReport {
  lines: BudgetLine[]
  total: number
  budget_limit?: number | null
  over_budget: number
}

export interface TraceEvent {
  node_id: string
  status: 'ok' | 'degraded' | 'failed' | 'skipped'
  duration_ms: number
  cache?: string | null
  tokens_in: number
  tokens_out: number
  cost: number
  error?: string | null
  meta: Record<string, unknown>
}

export interface ValidationIssue {
  code: string
  severity: 'blocking' | 'warning' | 'info'
  target: string
  message: string
  suggestion: string
}

export interface ValidationResult {
  issues: ValidationIssue[]
  repaired: boolean
  passed: boolean
}

export interface TripResult {
  request: TripFormData & { budget_limit?: number | null }
  days: DayView[]
  budget: BudgetReport
  validation: ValidationResult
  weather: WeatherView[]
  trace: TraceEvent[]
  degraded: boolean
  notes: string[]
}

export interface TripPlanResponse {
  success: boolean
  message: string
  data: TripResult
  trip_id: string
  request_id: string
  cached: boolean
}

export interface RecalculatePlan {
  days: Array<{
    date: string
    attraction_ids: string[]
    hotel_id: string
    meals: Array<{ type: string; restaurant_id: string }>
    transport_mode: string
    theme: string
  }>
  notes: string[]
}
