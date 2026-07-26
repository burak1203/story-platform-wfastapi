import { defineStore } from 'pinia'
import axios from 'axios'
import type { RegisterRequest, AuthenticationRequest, AuthenticationResponse } from '@/types/index'
// Relative /api: dev'de Vite proxy'si, prod'da Caddy backend'e yonlendirir
const API_URL = '/api/auth'

/**
 * JWT'nin payload'undaki kullanici adini okur (imza DOGRULANMAZ).
 * Yalnizca ARAYUZ icin: "sil"/"sabitle" dugmesini kime gosterecegimizi bilmek gibi.
 * Yetki kararlari SUNUCUDA verilir (403 doner) — buradaki deger kurcalansa bile
 * kullanici backend'de yetkisi olmayan bir sey yapamaz.
 */
function usernameFromToken(token: string | null): string | null {
  if (!token) return null
  try {
    const payload = token.split('.')[1]
    if (!payload) return null
    const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'))
    return JSON.parse(json).sub ?? null
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('token') || (null as string | null),
    isAuthenticated: !!localStorage.getItem('token'),
    isLoading: false,
    error: null as string | null,
  }),

  getters: {
    /** Giris yapan kullanicinin adi (yoksa null). Bkz. usernameFromToken — sadece arayuz icin. */
    username: (state): string | null => usernameFromToken(state.token),
  },

  actions: {
    // Axios'a token'ı global olarak ekleyen yardımcı metot
    setAxiosHeader() {
      if (this.token) {
        axios.defaults.headers.common['Authorization'] = `Bearer ${this.token}`
      } else {
        delete axios.defaults.headers.common['Authorization']
      }
    },

    async login(credentials: any) {
      this.isLoading = true
      this.error = null
      try {
        const response = await axios.post(`${API_URL}/authenticate`, credentials)
        this.token = response.data.token
        this.isAuthenticated = true
        localStorage.setItem('token', this.token!)
        this.setAxiosHeader()
      } catch (err: any) {
        this.error = err.response?.data?.detail || 'Giriş başarısız. Bilgilerinizi kontrol edin.'
        throw err
      } finally {
        this.isLoading = false
      }
    },

    async register(userData: any) {
      this.isLoading = true
      this.error = null
      try {
        const response = await axios.post(`${API_URL}/register`, userData)
        this.token = response.data.token
        this.isAuthenticated = true
        localStorage.setItem('token', this.token!)
        this.setAxiosHeader()
      } catch (err: any) {
        this.error =
          err.response?.data?.detail || 'Kayıt olunamadı. E-posta veya kullanıcı adı kullanılıyor olabilir.'
        throw err
      } finally {
        this.isLoading = false
      }
    },

    // Google Identity Services'ten gelen id_token ile giris; backend dogrulayip kendi JWT'mizi verir
    async googleLogin(idToken: string) {
      this.isLoading = true
      this.error = null
      try {
        const response = await axios.post(`${API_URL}/google`, { idToken })
        this.token = response.data.token
        this.isAuthenticated = true
        localStorage.setItem('token', this.token!)
        this.setAxiosHeader()
      } catch (err: any) {
        this.error = err.response?.data?.detail || 'Google ile giriş başarısız.'
        throw err
      } finally {
        this.isLoading = false
      }
    },

    logout() {
      this.token = null
      this.isAuthenticated = false
      localStorage.removeItem('token')
      this.setAxiosHeader()
    },
  },
})
