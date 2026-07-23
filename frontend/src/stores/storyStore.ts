import { defineStore } from 'pinia'
import axios from 'axios'
import type {
  StoryDetailResponse,
  StorySummaryResponse,
  CreateStoryRequest,
  ElementKind,
} from '../types'
import { useLlmKeyStore } from './llmKeyStore'

const API_URL = '/api/stories'
const ELEMENTS_URL = '/api/elements'

const LLM_KEY_MESSAGE = 'Set up your LLM provider (base URL + model + key) to generate chapters.'

// Backend ayar eksik/geçersiz dediyse ayar modalini açar; true dönerse hata ele alındı
function redirectToKeyModal(err: any): boolean {
  const detail = err?.response?.data?.detail
  if (detail === 'llm_config_missing' || detail === 'llm_key_invalid') {
    useLlmKeyStore().openModal()
    return true
  }
  return false
}

export const useStoryStore = defineStore('story', {
  state: () => ({
    story: null as StoryDetailResponse | null,
    myStories: [] as StorySummaryResponse[], // dashboard için hafif özet listesi
    isLoading: false,
    error: null as string | null,
    eventSource: null as EventSource | null,
    watchdogTimer: null as number | null,
  }),

  actions: {
    // dashboard'da gösterilecek tüm hikayeleri getirir
    async fetchMyStories() {
      this.isLoading = true
      this.error = null
      try {
        const response = await axios.get<StorySummaryResponse[]>(`${API_URL}/my-stories`)
        this.myStories = response.data
      } catch (err: any) {
        this.error = err.message || 'Hikayeler yüklenemedi.'
      } finally {
        this.isLoading = false
      }
    },

    // Sıfırdan hikaye oluşturur ve yönlendirme için döner
    async createStory(payload: CreateStoryRequest) {
      const llmKey = useLlmKeyStore()
      if (!llmKey.hasKey) {
        llmKey.openModal()
        this.error = LLM_KEY_MESSAGE
        throw new Error(LLM_KEY_MESSAGE)
      }

      this.isLoading = true
      this.error = null
      try {
        const response = await axios.post<StoryDetailResponse>(API_URL, payload)
        return response.data
      } catch (err: any) {
        this.error = redirectToKeyModal(err)
          ? LLM_KEY_MESSAGE
          : err.response?.data?.detail || err.message || 'Hikaye oluşturulamadı.'
        throw err
      } finally {
        this.isLoading = false
      }
    },

    async fetchStory(storyId: number) {
      this.isLoading = true
      this.error = null
      try {
        const response = await axios.get<StoryDetailResponse>(`${API_URL}/${storyId}`)
        this.story = response.data
        this.connectToStream(storyId)

        // butonları kilitli tut ve Watchdog'u başlat.
        if (this.story.status === 'PENDING' || this.story.status === 'GENERATING') {
          this.isLoading = true
          this.startWatchdog()
        } else {
          this.isLoading = false
        }
      } catch (err: any) {
        this.error = err.message || 'Hikaye yüklenemedi.'
        this.isLoading = false
      }
    },

    async deleteStory(storyId: number) {
      this.isLoading = true
      this.error = null
      try {
        await axios.delete(`${API_URL}/${storyId}`)
        // Silme başarılıysa o hikayeyi ekrandaki listeden anında uçur
        this.myStories = this.myStories.filter((s) => s.id !== storyId)
      } catch (err: any) {
        this.error = err.message || 'Hikaye silinemedi.'
      } finally {
        this.isLoading = false
      }
    },

    connectToStream(storyId: number) {
      this.disconnectStream()

      const token = localStorage.getItem('token')
      this.eventSource = new EventSource(`${API_URL}/${storyId}/stream?token=${token}`)

      this.eventSource.addEventListener('STORY_UPDATE', (event) => {
        const updatedData = JSON.parse(event.data)

        // Hata mesajı varsa
        if (updatedData.type === 'AI_ERROR') {
          this.error = updatedData.message
          this.isLoading = false
          this.stopWatchdog()
          return // İşlemi kes, hikaye metnini bozma
        }

        // NORMAL İŞLEYİŞ: Gelen veri gerçek bir hikaye güncellemesiyse
        this.story = updatedData
        this.error = null // Varsa eski hatayı temizle
        this.isLoading = false
        this.stopWatchdog()
      })

      this.eventSource.onerror = (err) => {
        this.disconnectStream()
      }
    },

    disconnectStream() {
      if (this.eventSource) {
        this.eventSource.close()
        this.eventSource = null
      }
      this.stopWatchdog()
    },

    async continueStory(storyId: number, userAction: string) {
      const llmKey = useLlmKeyStore()
      if (!llmKey.hasKey) {
        llmKey.openModal()
        this.error = LLM_KEY_MESSAGE
        return
      }

      this.isLoading = true
      this.error = null
      this.startWatchdog()

      try {
        await axios.post(`${API_URL}/${storyId}/continue`, {
          userAction: userAction,
        })
      } catch (err: any) {
        this.error = redirectToKeyModal(err)
          ? LLM_KEY_MESSAGE
          : err.response?.data?.detail || err.message || 'Hamle gönderilemedi.'
        this.stopWatchdog()
        this.isLoading = false // KRİTİK: Hata alırsan butonu kilitten kurtar
      }
    },

    startWatchdog() {
      this.stopWatchdog()
      this.watchdogTimer = window.setTimeout(() => {
        if (this.isLoading) {
          this.error = 'Yapay zeka çok yoğun, yanıt gecikti. Lütfen sayfayı yenileyin.'
          this.isLoading = false
          this.disconnectStream() // Tarayıcı (canceled) hatasının ana sebebi bu satırdır
        }
      }, 180000) // 60000'den 180000'e (3 dakika) çıkardık!
    },

    stopWatchdog() {
      if (this.watchdogTimer) {
        clearTimeout(this.watchdogTimer)
        this.watchdogTimer = null
      }
    },
    // SSE'yi koparmadan hikayeyi tazeler (varlık/özet düzenlemelerinden sonra)
    async refreshStory(storyId: number) {
      try {
        const response = await axios.get<StoryDetailResponse>(`${API_URL}/${storyId}`)
        this.story = response.data
      } catch (err: any) {
        this.error = err.response?.data?.detail || err.message || 'Hikaye yüklenemedi.'
      }
    },

    // Herhangi bir bölümün metnini düzenler; backend özeti ve vektörü yeniler,
    // bir sonraki üretime "burada şu değişti" notu düşer
    async editChapter(storyId: number, chapterIndex: number, newContent: string) {
      const llmKey = useLlmKeyStore()
      if (!llmKey.hasKey) {
        // Düzenleme sonrası yeniden özet kullanıcının anahtarıyla çıkarılır
        llmKey.openModal()
        this.error = LLM_KEY_MESSAGE
        throw new Error(LLM_KEY_MESSAGE)
      }

      this.isLoading = true
      this.error = null
      try {
        const response = await axios.put(`${API_URL}/${storyId}/chapters/${chapterIndex}`, {
          newContent,
        })
        this.story = response.data
      } catch (err: any) {
        this.error = redirectToKeyModal(err)
          ? LLM_KEY_MESSAGE
          : err.response?.data?.detail || err.message || 'Bölüm güncellenemedi.'
        throw err
      } finally {
        this.isLoading = false
      }
    },

    async editChapterSummary(storyId: number, chapterIndex: number, newSummary: string) {
      this.error = null
      try {
        const response = await axios.put(
          `${API_URL}/${storyId}/chapters/${chapterIndex}/summary`,
          { newSummary },
        )
        this.story = response.data
      } catch (err: any) {
        this.error = err.response?.data?.detail || err.message || 'Özet güncellenemedi.'
        throw err
      }
    },

    async updateSettings(storyId: number, stylePrompt: string, negativePrompt: string) {
      this.error = null
      try {
        const response = await axios.put(`${API_URL}/${storyId}/settings`, {
          stylePrompt,
          negativePrompt,
        })
        this.story = response.data
      } catch (err: any) {
        this.error = err.response?.data?.detail || err.message || 'Ayarlar kaydedilemedi.'
        throw err
      }
    },

    async addElement(kind: ElementKind, storyId: number, name: string, description: string) {
      this.error = null
      try {
        await axios.post(`${ELEMENTS_URL}/${kind}`, { storyId, name, description })
        await this.refreshStory(storyId)
      } catch (err: any) {
        this.error = err.response?.data?.detail || err.message || 'Öğe eklenemedi.'
        throw err
      }
    },

    async updateElement(
      kind: ElementKind,
      storyId: number,
      elementId: number,
      name: string,
      description: string,
    ) {
      this.error = null
      try {
        await axios.put(`${ELEMENTS_URL}/${kind}/${elementId}`, { name, description })
        await this.refreshStory(storyId)
      } catch (err: any) {
        this.error = err.response?.data?.detail || err.message || 'Öğe güncellenemedi.'
        throw err
      }
    },

    async deleteElement(kind: ElementKind, storyId: number, elementId: number) {
      this.error = null
      try {
        await axios.delete(`${ELEMENTS_URL}/${kind}/${elementId}`)
        await this.refreshStory(storyId)
      } catch (err: any) {
        this.error = err.response?.data?.detail || err.message || 'Öğe silinemedi.'
      }
    },
  },
})
