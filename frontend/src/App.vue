<script setup lang="ts">
import { computed } from 'vue'
import { RouterView } from 'vue-router'
import { NConfigProvider, darkTheme } from 'naive-ui'
import LlmKeyModal from '@/components/LlmKeyModal.vue'
import { useReaderPrefsStore } from '@/stores/readerPrefsStore'
import { darkThemeOverrides, lightThemeOverrides } from '@/theme/overrides'

// TEK tema anahtari: readerPrefsStore hem <html>'e "dark" sinifini koyuyor (Tailwind'in
// dark: varyantlari icin) hem de burada Naive UI'in temasini seciyor. Ayri bir tema
// anahtari OLMAMALI — olsaydi okurun sectigi tema ile bilesenlerin temasi ayrisirdi
// (koyu sayfada acik buton).
const prefs = useReaderPrefsStore()

const naiveTheme = computed(() => (prefs.theme === 'dark' ? darkTheme : null))
const naiveThemeOverrides = computed(() =>
  prefs.theme === 'dark' ? darkThemeOverrides : lightThemeOverrides,
)
</script>

<template>
  <!-- NGlobalStyle BILINCLI olarak yok: body arka planini Naive'e devretmek mevcut
       sayfalarin Tailwind arka planlarini ezerdi. Kabuk isi bu adimda degil. -->
  <NConfigProvider :theme="naiveTheme" :theme-overrides="naiveThemeOverrides">
    <RouterView />
    <LlmKeyModal />
  </NConfigProvider>
</template>
