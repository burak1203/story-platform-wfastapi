import { defineStore } from 'pinia'

// Okuma tercihleri yalnizca TARAYICIDA durur: sunucuya gonderilecek bir tarafi yok ve
// girissiz okur da ayni konforu gormeli. Tema <html> uzerindeki "dark" sinifiyla uygulanir
// (tailwind darkMode: 'class'); boylece sayfa gecislerinde titremez.

const THEME_KEY = 'reader_theme'
const FONT_KEY = 'reader_font_size'

export type ReaderTheme = 'dark' | 'light'

// Uzun okuma icin olcek. En kucugu 16px: 14px'te telefonda goz yoruluyor, bu bir okuma
// uygulamasi. Adimlar 2px — fark hissedilir ama duzen bozulmaz.
export const FONT_SIZES = [16, 18, 20, 22, 24] as const
const DEFAULT_FONT = 18

function loadTheme(): ReaderTheme {
  // Varsayilan KOYU: sitenin geri kalani koyu, ayrica hedef kitle (interactive fiction /
  // roleplay) agirlikli olarak koyu tema kullaniyor.
  return localStorage.getItem(THEME_KEY) === 'light' ? 'light' : 'dark'
}

function loadFontSize(): number {
  const stored = Number(localStorage.getItem(FONT_KEY))
  return (FONT_SIZES as readonly number[]).includes(stored) ? stored : DEFAULT_FONT
}

export const useReaderPrefsStore = defineStore('readerPrefs', {
  state: () => ({
    theme: loadTheme(),
    fontSize: loadFontSize(),
  }),

  getters: {
    canGrow: (state) => state.fontSize < FONT_SIZES[FONT_SIZES.length - 1]!,
    canShrink: (state) => state.fontSize > FONT_SIZES[0]!,
  },

  actions: {
    /** Temayi <html>'e uygular. Okuyucu sayfalari acilirken cagrilir. */
    applyTheme() {
      document.documentElement.classList.toggle('dark', this.theme === 'dark')
    },

    toggleTheme() {
      this.theme = this.theme === 'dark' ? 'light' : 'dark'
      localStorage.setItem(THEME_KEY, this.theme)
      this.applyTheme()
    },

    /** delta: +1 buyut, -1 kucult. Olcek disina TASMAZ. */
    stepFontSize(delta: number) {
      const index = FONT_SIZES.indexOf(this.fontSize as (typeof FONT_SIZES)[number])
      const next = FONT_SIZES[index + delta]
      if (next === undefined) return
      this.fontSize = next
      localStorage.setItem(FONT_KEY, String(next))
    },
  },
})
