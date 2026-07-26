<script setup lang="ts">
// Okuyucu sayfalarinin ortak ust cubugu. Okuma sayfasinda KULLANILMAZ — orasi dikkat
// dagitmayan kendi ince cubugunu kullanir.
import { RouterLink } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { useReaderPrefsStore } from '@/stores/readerPrefsStore'

const auth = useAuthStore()
const prefs = useReaderPrefsStore()
</script>

<template>
  <header
    class="sticky top-0 z-10 border-b border-slate-200 bg-white/95 backdrop-blur dark:border-slate-800 dark:bg-slate-900/95"
  >
    <!-- 375px'te: marka + ikonlar tek satirda sigar; etiketler sm'den itibaren acilir -->
    <div class="mx-auto flex h-14 max-w-5xl items-center gap-3 px-4">
      <RouterLink
        to="/"
        class="text-lg font-bold tracking-tight text-amber-600 dark:text-amber-500"
      >
        StoryPlatform
      </RouterLink>

      <div class="ml-auto flex items-center gap-1 sm:gap-2">
        <button
          type="button"
          @click="prefs.toggleTheme()"
          class="rounded-lg px-2 py-1.5 text-base text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          :aria-label="prefs.theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'"
        >
          {{ prefs.theme === 'dark' ? '☀' : '☾' }}
        </button>

        <template v-if="auth.isAuthenticated">
          <RouterLink
            to="/dashboard"
            class="rounded-lg px-3 py-1.5 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            Studio
          </RouterLink>
        </template>
        <template v-else>
          <RouterLink
            to="/login"
            class="rounded-lg bg-amber-600 px-3 py-1.5 text-sm font-semibold text-white transition-colors hover:bg-amber-500"
          >
            Sign in
          </RouterLink>
        </template>
      </div>
    </div>
  </header>
</template>
