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

export interface StoryDetailResponse {
  id: number
  title: string
  content: string
  status: string
  currentSummary: string | null
  actionCount: number
  stylePrompt: string | null
  negativePrompt: string | null
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