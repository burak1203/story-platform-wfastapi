export interface ElementDto {
  id: number
  name: string
  description: string
  status?: string | null
}

export interface ChapterDto {
  id: number
  index: number
  content: string
  summary: string | null
}

export type ElementKind = 'characters' | 'locations' | 'items'

// Dashboard listesi icin hafif ozet (bolum metni tasimaz; tam icerik detay ucundan gelir)
export interface StorySummaryResponse {
  id: number
  title: string
  status: string
  actionCount: number
  currentSummary: string | null
}

// Yazarin kalici talimatlari: tek metin degil, sirali madde listesi (tek tek acilip kapanir)
export type PromptItemKind = 'style' | 'negative'

export interface PromptItemDto {
  id: number
  kind: PromptItemKind
  text: string
  enabled: boolean
  order: number
}

export interface StoryDetailResponse {
  id: number
  title: string
  content: string
  status: string
  currentSummary: string | null
  actionCount: number
  /** Prompta tam metin girecek son bölüm sayısı (1-5) */
  lastChaptersFullText: number
  promptItems: PromptItemDto[]
  characters: ElementDto[]
  locations: ElementDto[]
  items: ElementDto[]
  chapters: ChapterDto[]
}

export interface RegisterRequest {
  username: string
  email?: string
  password: string
}

export interface AuthenticationRequest {
  username: string
  password: string
}

export interface AuthenticationResponse {
  token: string
}

export interface CreateStoryRequest {
  title: string
  startingPrompt: string
}