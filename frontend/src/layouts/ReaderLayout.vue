<script setup lang="ts">
// Okuyucu kabugu: ana sayfa, hikaye tanitimi, yazar profili.
// OKUMA SAYFASI BURAYA GIRMEZ — kendi ince cubugu var, kabuga sokmak cift baslik uretir.
import { computed, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { NButton, NIcon, NInput } from 'naive-ui'
import { MoonOutline, SearchOutline, SunnyOutline } from '@vicons/ionicons5'
import { useAuthStore } from '@/stores/authStore'
import { useReaderPrefsStore } from '@/stores/readerPrefsStore'

const auth = useAuthStore()
const prefs = useReaderPrefsStore()
const route = useRoute()
const router = useRouter()

// Genislik ROTA META'sindan gelir; kabuk sabit genislik dayatmaz. Aksi halde hikaye
// tanitiminin dar okunabilir kolonu ile ana sayfanin genis izgarasi ayni kaliba girer.
const widthClass = computed(() => (route.meta.width === 'narrow' ? 'max-w-3xl' : 'max-w-5xl'))

// Arama kutusu URL'i tek dogruluk kaynagi olarak kullanir: paylasilabilir ve geri tusuyla
// gezilebilir kalsin. Adres degisince (geri tusu, etiket temizleme) kutu da guncellenir.
const search = ref((route.query.q as string) || '')
watch(
  () => route.query.q,
  (q) => {
    search.value = (q as string) || ''
  },
)

function submitSearch() {
  const query: Record<string, string> = {}
  const q = search.value.trim()
  if (q) query.q = q
  // Etiket filtresi aramaya RAGMEN korunur (ikisi birlikte daraltir).
  const tag = route.query.tag as string
  if (tag) query.tag = tag
  router.push({ path: '/', query })
}
</script>

<template>
  <div class="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-900 dark:text-slate-100">
    <header
      class="sticky top-0 z-10 border-b border-slate-200 bg-white/95 backdrop-blur dark:border-slate-800 dark:bg-slate-900/95"
    >
      <!-- 375px: marka + arama + ikonlar tek satirda sigar; arama buyurken marka kismalar -->
      <div class="mx-auto flex h-14 max-w-5xl items-center gap-2 px-4 sm:gap-3">
        <RouterLink
          to="/"
          class="shrink-0 text-lg font-bold tracking-tight text-amber-600 dark:text-amber-500"
        >
          <!-- Mobilde kisa marka: tam ad aramaya yer birakmiyor -->
          <span class="hidden sm:inline">StoryPlatform</span>
          <span class="sm:hidden">SP</span>
        </RouterLink>

        <!-- Aktif vurgu sidebar'daki ile AYNI stil (bg-slate-100/800) — iki kabukta
             farkli gorunmesi "baska bir uygulamadaymisim" hissi verirdi. -->
        <nav class="hidden shrink-0 items-center gap-1 sm:flex">
          <RouterLink
            to="/"
            class="rounded-lg px-3 py-1.5 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            :class="route.name === 'home' ? 'bg-slate-100 dark:bg-slate-800' : ''"
          >
            Home
          </RouterLink>
        </nav>

        <form class="min-w-0 flex-1" @submit.prevent="submitSearch">
          <NInput
            v-model:value="search"
            type="text"
            placeholder="Search stories"
            :maxlength="200"
            clearable
            @keyup.enter="submitSearch"
          >
            <template #prefix>
              <NIcon :component="SearchOutline" />
            </template>
          </NInput>
        </form>

        <div class="flex shrink-0 items-center gap-1 sm:gap-2">
          <NButton
            quaternary
            circle
            :aria-label="prefs.theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'"
            @click="prefs.toggleTheme()"
          >
            <template #icon>
              <NIcon :component="prefs.theme === 'dark' ? SunnyOutline : MoonOutline" />
            </template>
          </NButton>

          <RouterLink v-if="auth.isAuthenticated" to="/dashboard">
            <NButton quaternary>Studio</NButton>
          </RouterLink>
          <RouterLink v-else to="/login">
            <NButton type="primary">Sign in</NButton>
          </RouterLink>
        </div>
      </div>
    </header>

    <main class="mx-auto px-4 py-6" :class="widthClass">
      <RouterView />
    </main>
  </div>
</template>
