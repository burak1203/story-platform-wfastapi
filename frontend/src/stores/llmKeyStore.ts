import { defineStore } from 'pinia'
import axios from 'axios'

const VALIDATE_URL = '/api/llm/validate'

// localStorage anahtarlari — uretim ayarlari YALNIZCA tarayicida yasar, sunucuya sadece
// istek header'i olarak gider (X-LLM-*), orada saklanmaz/loglanmaz.
const K = {
  provider: 'llm_provider',
  baseUrl: 'llm_base_url',
  model: 'llm_model',
  key: 'llm_api_key',
} as const

export interface ProviderPreset {
  id: string
  label: string
  baseUrl: string
  model: string // onerilen varsayilan model (kullanici degistirebilir)
  keyHint: string
  keyUrl: string
}

// Hazir saglayicilar: secince base URL otomatik dolar. "custom" = elle base URL.
export const PROVIDERS: ProviderPreset[] = [
  { id: 'deepseek', label: 'DeepSeek', baseUrl: 'https://api.deepseek.com', model: 'deepseek-v4-flash', keyHint: 'sk-...', keyUrl: 'https://platform.deepseek.com/api_keys' },
  { id: 'openrouter', label: 'OpenRouter', baseUrl: 'https://openrouter.ai/api/v1', model: 'deepseek/deepseek-v4-flash', keyHint: 'sk-or-...', keyUrl: 'https://openrouter.ai/keys' },
  { id: 'gemini', label: 'Google Gemini', baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai/', model: 'gemini-3-flash', keyHint: 'AIza...', keyUrl: 'https://aistudio.google.com/apikey' },
  { id: 'openai', label: 'OpenAI', baseUrl: 'https://api.openai.com/v1', model: 'gpt-4o-mini', keyHint: 'sk-...', keyUrl: 'https://platform.openai.com/api-keys' },
  { id: 'custom', label: 'Custom (manual base URL)', baseUrl: '', model: '', keyHint: '', keyUrl: '' },
]

const DEFAULT_PRESET = PROVIDERS[0] as ProviderPreset

export function presetOf(id: string): ProviderPreset {
  return PROVIDERS.find((p) => p.id === id) ?? DEFAULT_PRESET
}

export const useLlmKeyStore = defineStore('llmKey', {
  state: () => ({
    provider: localStorage.getItem(K.provider) || 'deepseek',
    baseUrl: localStorage.getItem(K.baseUrl) || presetOf(localStorage.getItem(K.provider) || 'deepseek').baseUrl,
    model: localStorage.getItem(K.model) || presetOf(localStorage.getItem(K.provider) || 'deepseek').model,
    key: localStorage.getItem(K.key) || '',
    isModalOpen: false,
    isValidating: false,
    validationResult: null as boolean | null,
  }),

  getters: {
    // Uretim icin dordu de dolu olmali: saglayici + base URL + model + anahtar
    hasKey: (state) => !!(state.provider && state.baseUrl && state.model && state.key),
  },

  actions: {
    openModal() {
      this.isModalOpen = true
    },

    closeModal() {
      this.isModalOpen = false
      this.validationResult = null
    },

    // Kaydedilmis ayarlari header olarak dondurur (main.ts interceptor kullanir)
    headers(): Record<string, string> {
      if (!this.key) return {}
      return {
        'X-LLM-Provider': this.provider,
        'X-LLM-Base-URL': this.baseUrl,
        'X-LLM-Model': this.model,
        'X-LLM-API-Key': this.key,
      }
    },

    saveConfig(cfg: { provider: string; baseUrl: string; model: string; key: string }) {
      this.provider = cfg.provider
      this.baseUrl = cfg.baseUrl.trim()
      this.model = cfg.model.trim()
      this.key = cfg.key.trim()
      localStorage.setItem(K.provider, this.provider)
      localStorage.setItem(K.baseUrl, this.baseUrl)
      localStorage.setItem(K.model, this.model)
      if (this.key) localStorage.setItem(K.key, this.key)
      else localStorage.removeItem(K.key)
      this.validationResult = null
    },

    async validate(cfg: { provider: string; baseUrl: string; model: string; key: string }): Promise<boolean> {
      this.isValidating = true
      this.validationResult = null
      try {
        const response = await axios.post(VALIDATE_URL, null, {
          headers: {
            'X-LLM-Provider': cfg.provider,
            'X-LLM-Base-URL': cfg.baseUrl.trim(),
            'X-LLM-Model': cfg.model.trim(),
            'X-LLM-API-Key': cfg.key.trim(),
          },
        })
        this.validationResult = response.data?.valid === true
      } catch {
        this.validationResult = false
      } finally {
        this.isValidating = false
      }
      return this.validationResult === true
    },
  },
})
