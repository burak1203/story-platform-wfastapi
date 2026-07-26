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
  publishing: PublishingDto
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
// --- Okuyucu platformu (public uclar) ---------------------------------------------------
// Bu tipler backend'deki Public* DTO'larinin AYNASIDIR. Yazar tarafi tipleriyle (ör.
// StoryDetailResponse) bilerek karistirilmaz: okuyucuya giden alan kumesi kasitli olarak
// dardir, ikisini tek tipte birlestirmek o siniri gorunmez kilar.

export type Visibility = 'private' | 'unlisted' | 'public'

export interface PublicStoryCard {
  id: number
  title: string
  description: string | null
  tags: string[]
  author: string
  chapterCount: number
  likeCount: number
  publishedAt: string | null
}

export interface PublicChapterRef {
  index: number
  likeCount: number
  commentCount: number
}

export interface PublicStoryDetail {
  id: number
  title: string
  description: string | null
  tags: string[]
  author: string
  visibility: Visibility
  isShowcase: boolean
  publishedAt: string | null
  chapterCount: number
  likeCount: number
  chapters: PublicChapterRef[]
}

export interface PublicChapterView {
  storyId: number
  storyTitle: string
  author: string
  index: number
  content: string
  likeCount: number
  liked: boolean
  previousIndex: number | null
  nextIndex: number | null
}

export interface PublicAuthorProfile {
  username: string
  joinedAt: string
  totalLikes: number
  stories: PublicStoryCard[]
}

export interface ChapterLikeState {
  likeCount: number
  liked: boolean
}

export interface PublicCommentDto {
  id: number
  author: string
  body: string
  /** Yorumcu hikayenin yazari mi (rozet icin) */
  isAuthor: boolean
  isPinned: boolean
  createdAt: string
}

export interface PublicCommentPage {
  total: number
  comments: PublicCommentDto[]
}

// Yazar tarafi: yayimlama ayarlari (StoryDetailResponse.publishing)
export interface PublishingDto {
  visibility: Visibility
  description: string | null
  tags: string[]
  isAdult: boolean
  isShowcase: boolean
  publishedAt: string | null
}
