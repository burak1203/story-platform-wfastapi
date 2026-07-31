import type { GlobalThemeOverrides } from 'naive-ui'

// Naive UI'in hazir temasini DOGRUDAN kullanmiyoruz: uzerine proje token'lari binen bir
// katman var. Renk / yuvarlaklik degistirmek gerektiginde tek yer burasi — bilesenlere
// dokunulmadan tema donuyor.
//
// Naive UI'da "preset sarmalama" dogal olarak budur: darkTheme/lightTheme tabani verir,
// bu nesne uzerine yazar (bkz. App.vue, NConfigProvider :theme-overrides).

// Marka rengi (indigo). Tek yerde durur ki acik ve koyu tema ayrisma riski olmasin.
const PRIMARY = '#4f46e5' // indigo-600
const PRIMARY_HOVER = '#6366f1' // indigo-500
const PRIMARY_PRESSED = '#4338ca' // indigo-700

const common = {
  primaryColor: PRIMARY,
  primaryColorHover: PRIMARY_HOVER,
  primaryColorPressed: PRIMARY_PRESSED,
  primaryColorSuppl: PRIMARY_HOVER,

  // Kose yuvarlakligi Tailwind'in rounded-md/lg olcegiyle ayni dursun, yoksa Naive
  // bilesenleri sayfaya yapistirilmis gibi gorunur.
  borderRadius: '6px',
  borderRadiusSmall: '4px',
}

/** Acik tema uzerine binen proje token'lari. */
export const lightThemeOverrides: GlobalThemeOverrides = {
  common,
}

/** Koyu tema uzerine binen proje token'lari. */
export const darkThemeOverrides: GlobalThemeOverrides = {
  common: {
    ...common,
    // Koyu temada yuzeyler slate: okuma sayfasinin mevcut koyu paleti de slate.
    bodyColor: '#0f172a', // slate-900
    cardColor: '#1e293b', // slate-800
    modalColor: '#1e293b',
    popoverColor: '#1e293b',
  },
}
