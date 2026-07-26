import { defineStore } from 'pinia'
import axios from 'axios'
import type {
  ChapterLikeState,
  PublicAuthorProfile,
  PublicChapterView,
  PublicCommentDto,
  PublicCommentPage,
  PublicStoryCard,
  PublicStoryDetail,
} from '@/types'

// Okuyucu tarafi API'si. Yazar tarafindaki storyStore'dan AYRI tutuluyor: farkli uclar,
// farkli tipler ve farkli erisim kurallari (cogu giris istemez). Ikisini birlestirmek
// yazar verisinin okuyucu ekranina sizmasini kolaylastirirdi.

const API_URL = '/api/public'

export const PAGE_SIZE = 12
export const COMMENT_PAGE_SIZE = 20

/** Backend 404'u "yok" demek; okuyucu icin bu bir cokme degil, "bulunamadi" ekrani. */
function isNotFound(err: any): boolean {
  return err?.response?.status === 404
}

function message(err: any, fallback: string): string {
  return err?.response?.data?.detail || err?.message || fallback
}

export const useReaderStore = defineStore('reader', {
  state: () => ({
    // Ana sayfa
    cards: [] as PublicStoryCard[],
    hasMore: false,
    // Hikaye / okuma / profil
    story: null as PublicStoryDetail | null,
    chapter: null as PublicChapterView | null,
    profile: null as PublicAuthorProfile | null,
    // Yorumlar
    comments: [] as PublicCommentDto[],
    commentTotal: 0,

    isLoading: false,
    isLoadingMore: false,
    notFound: false,
    error: null as string | null,
  }),

  actions: {
    /** Ana sayfa listesi. `append` ise "daha fazla yukle", degilse bastan arama. */
    async fetchStories(params: { q?: string; tag?: string; append?: boolean } = {}) {
      const append = params.append === true
      if (append) this.isLoadingMore = true
      else this.isLoading = true
      this.error = null
      try {
        const response = await axios.get<PublicStoryCard[]>(`${API_URL}/stories`, {
          params: {
            q: params.q || undefined,
            tag: params.tag || undefined,
            limit: PAGE_SIZE,
            offset: append ? this.cards.length : 0,
          },
        })
        this.cards = append ? [...this.cards, ...response.data] : response.data
        // Tam sayfa geldiyse devami olabilir; eksik geldiyse liste bitmistir.
        this.hasMore = response.data.length === PAGE_SIZE
      } catch (err: any) {
        this.error = message(err, 'Stories could not be loaded.')
      } finally {
        this.isLoading = false
        this.isLoadingMore = false
      }
    },

    async fetchStory(storyId: number) {
      this.isLoading = true
      this.error = null
      this.notFound = false
      this.story = null
      try {
        const response = await axios.get<PublicStoryDetail>(`${API_URL}/stories/${storyId}`)
        this.story = response.data
      } catch (err: any) {
        if (isNotFound(err)) this.notFound = true
        else this.error = message(err, 'Story could not be loaded.')
      } finally {
        this.isLoading = false
      }
    },

    async fetchChapter(storyId: number, index: number) {
      this.isLoading = true
      this.error = null
      this.notFound = false
      this.chapter = null
      try {
        const response = await axios.get<PublicChapterView>(
          `${API_URL}/stories/${storyId}/chapters/${index}`,
        )
        this.chapter = response.data
      } catch (err: any) {
        if (isNotFound(err)) this.notFound = true
        else this.error = message(err, 'Chapter could not be loaded.')
      } finally {
        this.isLoading = false
      }
    },

    async fetchProfile(username: string) {
      this.isLoading = true
      this.error = null
      this.notFound = false
      this.profile = null
      try {
        const response = await axios.get<PublicAuthorProfile>(`${API_URL}/users/${username}`)
        this.profile = response.data
      } catch (err: any) {
        if (isNotFound(err)) this.notFound = true
        else this.error = message(err, 'Profile could not be loaded.')
      } finally {
        this.isLoading = false
      }
    },

    /** Begeniyi cevirir. Sunucu guncel sayaci dondugu icin yerel tahmin yapilmaz. */
    async toggleLike(storyId: number, index: number) {
      if (!this.chapter) return
      const url = `${API_URL}/stories/${storyId}/chapters/${index}/like`
      try {
        const response = this.chapter.liked
          ? await axios.delete<ChapterLikeState>(url)
          : await axios.post<ChapterLikeState>(url)
        this.chapter.liked = response.data.liked
        this.chapter.likeCount = response.data.likeCount
      } catch (err: any) {
        this.error = message(err, 'Your like could not be saved.')
      }
    },

    async fetchComments(storyId: number, index: number, append = false) {
      try {
        const response = await axios.get<PublicCommentPage>(
          `${API_URL}/stories/${storyId}/chapters/${index}/comments`,
          { params: { limit: COMMENT_PAGE_SIZE, offset: append ? this.comments.length : 0 } },
        )
        this.comments = append ? [...this.comments, ...response.data.comments] : response.data.comments
        this.commentTotal = response.data.total
      } catch (err: any) {
        this.error = message(err, 'Comments could not be loaded.')
      }
    },

    async addComment(storyId: number, index: number, body: string) {
      const response = await axios.post<PublicCommentDto>(
        `${API_URL}/stories/${storyId}/chapters/${index}/comments`,
        { body },
      )
      // Sabitlenmemis yorumlar kronolojik: yeni yorum sona eklenir.
      this.comments = [...this.comments, response.data]
      this.commentTotal += 1
    },

    async deleteComment(storyId: number, index: number, commentId: number) {
      await axios.delete(`${API_URL}/stories/${storyId}/chapters/${index}/comments/${commentId}`)
      this.comments = this.comments.filter((c) => c.id !== commentId)
      this.commentTotal = Math.max(0, this.commentTotal - 1)
    },

    async pinComment(storyId: number, index: number, commentId: number, pinned: boolean) {
      await axios.put(
        `${API_URL}/stories/${storyId}/chapters/${index}/comments/${commentId}/pin`,
        { pinned },
      )
      // Siralama sunucuda belirleniyor (sabitlenenler ustte) — listeyi yeniden cek.
      await this.fetchComments(storyId, index)
    },
  },
})
