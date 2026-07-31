<script setup lang="ts">
// Yazar kabugu: dashboard, hikaye duzenleme, ayarlar.
//
// Masaustunde UST CUBUK YOK: /dashboard ve /studio/:id kendi basliklarini tasiyor,
// kabuk bir cubuk daha koyunca cift baslik oluyordu. Tema dugmesi rayin altinda.
// Mobilde yalnizca hamburger tasiyan ince bir cubuk var (ray gizli oldugu icin sart).
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { NButton, NIcon } from 'naive-ui'
import {
  ArrowBackOutline,
  BookOutline,
  GridOutline,
  MenuOutline,
  MoonOutline,
  PinOutline,
  SettingsOutline,
  SunnyOutline,
} from '@vicons/ionicons5'
import { useReaderPrefsStore } from '@/stores/readerPrefsStore'
import { useStoryStore } from '@/stores/storyStore'

const PIN_KEY = 'studio_sidebar_pinned'
const DESKTOP_QUERY = '(min-width: 1024px)'
// Kazara tetiklenmeyi onler: farenin ray uzerinden gecip gitmesi acmasin, ray ile
// icerik arasinda gidip gelirken de her seferinde kapanip acilmasin.
const OPEN_DELAY_MS = 150
const CLOSE_DELAY_MS = 300
// Rayda gosterilecek hikaye sayisi. Liste id DESC geliyor, yani ilk N = son N hikaye.
const RECENT_STORY_COUNT = 8

const prefs = useReaderPrefsStore()
const storyStore = useStoryStore()
const route = useRoute()

const isDesktop = ref(false)
const pinned = ref(localStorage.getItem(PIN_KEY) === '1')
const hovering = ref(false)
const focusWithin = ref(false)
const drawerOpen = ref(false)

let openTimer: number | null = null
let closeTimer: number | null = null
let media: MediaQueryList | null = null

const recentStories = computed(() => storyStore.myStories.slice(0, RECENT_STORY_COUNT))
const activeStoryId = computed(() => (route.name === 'studio' ? Number(route.params.id) : null))

// Ray GENIS mi? Masaustunde: sabitlenmis, fare uzerinde ya da odak icinde.
const railExpanded = computed(
  () => isDesktop.value && (pinned.value || hovering.value || focusWithin.value),
)
// Icerik YALNIZCA sabitlemede itilir. Hover ile acilma overlay'dir: sayfa daralmaz,
// yoksa fare gezdirmek butun duzeni oynatirdi.
const contentPushed = computed(() => isDesktop.value && pinned.value)

function clearTimers() {
  if (openTimer !== null) window.clearTimeout(openTimer)
  if (closeTimer !== null) window.clearTimeout(closeTimer)
  openTimer = closeTimer = null
}

function onRailEnter() {
  if (!isDesktop.value) return // mobilde hover YOK
  clearTimers()
  openTimer = window.setTimeout(() => (hovering.value = true), OPEN_DELAY_MS)
}

function onRailLeave() {
  if (!isDesktop.value) return
  clearTimers()
  closeTimer = window.setTimeout(() => (hovering.value = false), CLOSE_DELAY_MS)
}

function togglePin() {
  pinned.value = !pinned.value
  localStorage.setItem(PIN_KEY, pinned.value ? '1' : '0')
}

// --- Mobil drawer: odak tuzagi + Esc ---
const drawerEl = ref<HTMLElement | null>(null)

function focusables(): HTMLElement[] {
  if (!drawerEl.value) return []
  return Array.from(
    drawerEl.value.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((el) => el.offsetParent !== null)
}

function onKeydown(event: KeyboardEvent) {
  if (!drawerOpen.value) return

  if (event.key === 'Escape') {
    drawerOpen.value = false
    return
  }

  // Odak tuzagi: drawer acikken sekme arkadaki sayfaya kacmamali, yoksa ekranda
  // gorunmeyen baglantilara odaklanilir.
  if (event.key !== 'Tab') return
  const items = focusables()
  if (!items.length) return
  const first = items[0]!
  const last = items[items.length - 1]!
  const active = document.activeElement as HTMLElement | null

  if (event.shiftKey && (active === first || !drawerEl.value?.contains(active))) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && active === last) {
    event.preventDefault()
    first.focus()
  }
}

function applyMedia(matches: boolean) {
  isDesktop.value = matches
  if (matches) {
    drawerOpen.value = false // masaustune gecince drawer asili kalmasin
  } else {
    clearTimers()
    hovering.value = false
    focusWithin.value = false
  }
}

// Adlandirilmis handler: inline arrow ile eklenirse unmount'ta KALDIRILAMAZ.
function onMediaChange(event: MediaQueryListEvent) {
  applyMedia(event.matches)
}

const hamburgerEl = ref<HTMLElement | null>(null)

onMounted(() => {
  media = window.matchMedia(DESKTOP_QUERY)
  applyMedia(media.matches)
  media.addEventListener('change', onMediaChange)
  document.addEventListener('keydown', onKeydown)

  // Liste elde yoksa ceker; varsa hicbir sey yapmaz (bkz. store: ensureMyStories).
  storyStore.ensureMyStories()
})

onBeforeUnmount(() => {
  clearTimers()
  document.removeEventListener('keydown', onKeydown)
  media?.removeEventListener('change', onMediaChange)
  document.body.style.overflow = ''
})

watch(
  () => route.fullPath,
  () => {
    drawerOpen.value = false // rota degisince drawer otomatik kapanir
    storyStore.ensureMyStories() // olusturmadan sonra bayrak dustuyse burada tazelenir
  },
)

watch(drawerOpen, async (open) => {
  // Drawer acikken arkadaki sayfa kaymasin
  document.body.style.overflow = open ? 'hidden' : ''

  if (open) {
    // Odagi drawer'in ICINE tasi. Tasimazsak odak disaridaki hamburger'da kalir ve ilk
    // Tab tuzagin disina, ekranda gorunmeyen baglantilara gider.
    await nextTick()
    focusables()[0]?.focus()
  } else {
    // Kapaninca odak tetikleyen dugmeye donsun; aksi halde odak <body>'ye duser ve
    // klavye kullanicisi listenin basina savrulur.
    hamburgerEl.value?.focus()
  }
})
</script>

<template>
  <div class="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-900 dark:text-slate-100">
    <!-- ================= MASAUSTU RAY ================= -->
    <!-- fixed + z-30: overlay olarak acilir, icerigi itmez. Genislik gecisi
         prefers-reduced-motion altinda global kuralla zaten sonuyor. -->
    <aside
      class="fixed inset-y-0 left-0 z-30 hidden flex-col border-r border-slate-200 bg-white transition-[width] duration-200 dark:border-slate-800 dark:bg-slate-950 lg:flex"
      :class="railExpanded ? 'w-60' : 'w-16'"
      @mouseenter="onRailEnter"
      @mouseleave="onRailLeave"
      @focusin="focusWithin = true"
      @focusout="focusWithin = false"
    >
      <div
        class="flex h-14 items-center gap-1 border-b border-slate-200 px-3 dark:border-slate-800"
      >
        <RouterLink
          to="/dashboard"
          class="min-w-0 flex-1 truncate text-lg font-bold tracking-tight text-amber-600 dark:text-amber-500"
        >
          <span v-if="railExpanded">StoryPlatform</span>
          <span v-else>SP</span>
        </RouterLink>
        <NButton
          v-if="railExpanded"
          quaternary
          circle
          size="small"
          :aria-label="pinned ? 'Unpin sidebar' : 'Pin sidebar open'"
          :aria-pressed="pinned"
          @click="togglePin"
        >
          <template #icon>
            <NIcon :component="PinOutline" :class="pinned ? 'text-amber-600' : ''" />
          </template>
        </NButton>
      </div>

      <nav class="flex-1 overflow-y-auto overflow-x-hidden p-2">
        <RouterLink
          to="/dashboard"
          class="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          :class="route.name === 'dashboard' ? 'bg-slate-100 dark:bg-slate-800' : ''"
          :title="railExpanded ? undefined : 'Dashboard'"
        >
          <NIcon :component="GridOutline" class="shrink-0" />
          <span v-if="railExpanded" class="truncate">Dashboard</span>
        </RouterLink>

        <p
          v-if="railExpanded"
          class="mt-4 px-3 pb-1 text-xs font-semibold uppercase tracking-wide text-slate-400"
        >
          My stories
        </p>
        <RouterLink
          v-for="story in recentStories"
          :key="story.id"
          :to="`/studio/${story.id}`"
          class="mt-0.5 flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          :class="activeStoryId === story.id ? 'bg-slate-100 font-medium dark:bg-slate-800' : ''"
          :title="railExpanded ? undefined : story.title"
        >
          <NIcon :component="BookOutline" class="shrink-0" />
          <span v-if="railExpanded" class="truncate">{{ story.title }}</span>
        </RouterLink>

        <RouterLink
          to="/settings"
          class="mt-4 flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          :title="railExpanded ? undefined : 'Settings'"
        >
          <NIcon :component="SettingsOutline" class="shrink-0" />
          <span v-if="railExpanded" class="truncate">Settings</span>
        </RouterLink>
      </nav>

      <div class="border-t border-slate-200 p-2 dark:border-slate-800">
        <button
          type="button"
          class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          :aria-label="prefs.theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'"
          :title="railExpanded ? undefined : 'Toggle theme'"
          @click="prefs.toggleTheme()"
        >
          <NIcon
            :component="prefs.theme === 'dark' ? SunnyOutline : MoonOutline"
            class="shrink-0"
          />
          <span v-if="railExpanded" class="truncate">
            {{ prefs.theme === 'dark' ? 'Light theme' : 'Dark theme' }}
          </span>
        </button>
        <RouterLink
          to="/"
          class="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          :title="railExpanded ? undefined : 'Back to site'"
        >
          <NIcon :component="ArrowBackOutline" class="shrink-0" />
          <span v-if="railExpanded" class="truncate">Back to site</span>
        </RouterLink>
      </div>
    </aside>

    <!-- ================= MOBIL DRAWER ================= -->
    <div
      v-if="drawerOpen"
      class="fixed inset-0 z-40 bg-black/50 lg:hidden"
      @click="drawerOpen = false"
    />
    <aside
      v-if="drawerOpen"
      ref="drawerEl"
      class="fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950 lg:hidden"
    >
      <div class="flex h-14 items-center border-b border-slate-200 px-4 dark:border-slate-800">
        <span class="text-lg font-bold tracking-tight text-amber-600 dark:text-amber-500">
          StoryPlatform
        </span>
      </div>
      <nav class="flex-1 overflow-y-auto p-2">
        <RouterLink
          to="/dashboard"
          class="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          :class="route.name === 'dashboard' ? 'bg-slate-100 dark:bg-slate-800' : ''"
        >
          <NIcon :component="GridOutline" class="shrink-0" />
          Dashboard
        </RouterLink>

        <p class="mt-4 px-3 pb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          My stories
        </p>
        <RouterLink
          v-for="story in recentStories"
          :key="story.id"
          :to="`/studio/${story.id}`"
          class="mt-0.5 flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          :class="activeStoryId === story.id ? 'bg-slate-100 font-medium dark:bg-slate-800' : ''"
        >
          <NIcon :component="BookOutline" class="shrink-0" />
          <span class="truncate">{{ story.title }}</span>
        </RouterLink>

        <RouterLink
          to="/settings"
          class="mt-4 flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          <NIcon :component="SettingsOutline" class="shrink-0" />
          Settings
        </RouterLink>
      </nav>
      <div class="border-t border-slate-200 p-2 dark:border-slate-800">
        <button
          type="button"
          class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          @click="prefs.toggleTheme()"
        >
          <NIcon
            :component="prefs.theme === 'dark' ? SunnyOutline : MoonOutline"
            class="shrink-0"
          />
          {{ prefs.theme === 'dark' ? 'Light theme' : 'Dark theme' }}
        </button>
        <RouterLink
          to="/"
          class="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          <NIcon :component="ArrowBackOutline" class="shrink-0" />
          Back to site
        </RouterLink>
      </div>
    </aside>

    <!-- ================= ICERIK ================= -->
    <!-- Sol bosluk ray genisligi kadar; YALNIZCA sabitlemede genisler (overlay itmez). -->
    <div class="transition-[padding] duration-200" :class="contentPushed ? 'lg:pl-60' : 'lg:pl-16'">
      <!-- Mobil ust cubuk: SADECE hamburger. Masaustunde yok. -->
      <header
        class="sticky top-0 z-20 flex h-12 items-center border-b border-slate-200 bg-white/95 px-2 backdrop-blur dark:border-slate-800 dark:bg-slate-900/95 lg:hidden"
      >
        <!-- Native <button>: ref'in DOM elemanini vermesi gerekiyor (odagi buraya geri
             donduruyoruz). Bilesen ref'i instance dondurur, .$el ile ugrasmaya degmez. -->
        <button
          ref="hamburgerEl"
          type="button"
          class="rounded-lg p-2 text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          aria-label="Open menu"
          :aria-expanded="drawerOpen"
          @click="drawerOpen = true"
        >
          <NIcon :component="MenuOutline" size="22" />
        </button>
      </header>

      <main class="min-w-0">
        <RouterView />
      </main>
    </div>
  </div>
</template>
