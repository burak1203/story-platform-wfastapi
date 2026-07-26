<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useReaderStore } from '@/stores/readerStore'
import { useReaderPrefsStore } from '@/stores/readerPrefsStore'
import { useAuthStore } from '@/stores/authStore'
import CommentSection from '@/components/CommentSection.vue'

// OKUMA SAYFASI — urunun en cok vakit gecirilen ekrani.
// Tasarim kararlari:
//  * Ust cubuk INCE ve az ogeli: okurken kalan her piksel metne gitsin.
//  * Satir uzunlugu max-w-2xl ile sinirli — tam genislikte satirlar gozun satir basini
//    kaybetmesine yol acar; uzun okumada en cok yoran sey budur.
//  * Satir araligi 1.75: govde metni icin sik ve rahat.
//  * Font boyutu ve tema okurun; localStorage'da kalir (bkz. readerPrefsStore).

const reader = useReaderStore()
const prefs = useReaderPrefsStore()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const storyId = computed(() => Number(route.params.id))
const chapterIndex = computed(() => Number(route.params.index))

async function load() {
  if (!Number.isFinite(storyId.value) || !Number.isFinite(chapterIndex.value)) return
  await reader.fetchChapter(storyId.value, chapterIndex.value)
  if (reader.chapter) await reader.fetchComments(storyId.value, chapterIndex.value)
  // Yeni bolume gecince en basa don — okur onceki bolumun sonunda kalmasin
  window.scrollTo({ top: 0 })
}

onMounted(() => {
  load()
})

// Ayni bilesen icinde bolum degistiginde (onceki/sonraki) yeniden yukle
watch(chapterIndex, load)

function onLike() {
  if (!auth.isAuthenticated) {
    // Hata degil, YONLENDIRME: giristen sonra bu bolume geri doner
    router.push({ path: '/login', query: { redirect: route.fullPath } })
    return
  }
  reader.toggleLike(storyId.value, chapterIndex.value)
}
</script>

<template>
  <div class="min-h-screen bg-white text-slate-900 dark:bg-slate-900 dark:text-slate-100">
    <!-- INCE ust cubuk: geri + font + tema. 375px'te hepsi tek satirda siğar. -->
    <header
      class="sticky top-0 z-10 border-b border-slate-200 bg-white/95 backdrop-blur dark:border-slate-800 dark:bg-slate-900/95"
    >
      <div class="mx-auto flex h-12 max-w-2xl items-center gap-2 px-3">
        <RouterLink
          :to="`/s/${storyId}`"
          class="shrink-0 rounded-lg px-2 py-1.5 text-sm text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          aria-label="Back to story"
        >
          ‹ Story
        </RouterLink>

        <!-- Baslik dar ekranda tasmasin: tek satir + ellipsis -->
        <span
          v-if="reader.chapter"
          class="min-w-0 flex-1 truncate text-center text-sm font-medium text-slate-500 dark:text-slate-400"
        >{{ reader.chapter.storyTitle }}</span>

        <div class="flex shrink-0 items-center">
          <button
            type="button"
            @click="prefs.stepFontSize(-1)"
            :disabled="!prefs.canShrink"
            class="rounded-lg px-2 py-1.5 text-xs transition-colors hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-800"
            aria-label="Decrease text size"
          >
            A−
          </button>
          <button
            type="button"
            @click="prefs.stepFontSize(1)"
            :disabled="!prefs.canGrow"
            class="rounded-lg px-2 py-1.5 text-base transition-colors hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-800"
            aria-label="Increase text size"
          >
            A+
          </button>
          <button
            type="button"
            @click="prefs.toggleTheme()"
            class="rounded-lg px-2 py-1.5 text-base transition-colors hover:bg-slate-100 dark:hover:bg-slate-800"
            :aria-label="prefs.theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'"
          >
            {{ prefs.theme === 'dark' ? '☀' : '☾' }}
          </button>
        </div>
      </div>
    </header>

    <main class="mx-auto max-w-2xl px-5 pb-16 pt-6">
      <p v-if="reader.isLoading" class="py-16 text-center text-slate-500">Loading…</p>

      <div v-else-if="reader.notFound" class="py-16 text-center">
        <p class="text-lg font-semibold">Chapter not found</p>
        <p class="mt-2 text-sm text-slate-500 dark:text-slate-400">
          This story may be private or the chapter does not exist.
        </p>
        <RouterLink to="/" class="mt-4 inline-block text-amber-600 underline dark:text-amber-500">
          Back to home
        </RouterLink>
      </div>

      <template v-else-if="reader.chapter">
        <h1 class="text-xl font-bold sm:text-2xl">Chapter {{ reader.chapter.index }}</h1>
        <RouterLink
          :to="`/u/${reader.chapter.author}`"
          class="mt-1 inline-block text-sm text-amber-600 hover:underline dark:text-amber-500"
        >
          {{ reader.chapter.author }}
        </RouterLink>

        <!-- BOLUM METNI. v-html YOK: LLM/kullanici uretimi metin dogrudan text olarak
             basilir, pre-wrap paragraf bosluklarini korur. Font boyutu ve satir araligi
             okurun tercihine gore satir ici stille uygulanir. -->
        <article
          class="mt-6 whitespace-pre-wrap break-words font-serif text-slate-800 dark:text-slate-200"
          :style="{ fontSize: prefs.fontSize + 'px', lineHeight: '1.75' }"
        >{{ reader.chapter.content }}</article>

        <!-- Begeni -->
        <div class="mt-10 flex justify-center">
          <button
            type="button"
            @click="onLike"
            class="flex items-center gap-2 rounded-full border px-5 py-2.5 text-sm font-medium transition-colors"
            :class="
              reader.chapter.liked
                ? 'border-red-500 bg-red-50 text-red-600 dark:bg-red-500/10 dark:text-red-400'
                : 'border-slate-300 text-slate-600 hover:border-red-400 hover:text-red-600 dark:border-slate-700 dark:text-slate-300'
            "
            :aria-pressed="reader.chapter.liked"
          >
            <span class="text-lg leading-none">{{ reader.chapter.liked ? '♥' : '♡' }}</span>
            <span>{{ reader.chapter.likeCount }}</span>
          </button>
        </div>

        <!-- Gezinme: 375px'te iki esit dugme yan yana rahat sigar (min-w-0 + truncate) -->
        <nav class="mt-8 flex gap-3">
          <RouterLink
            v-if="reader.chapter.previousIndex !== null"
            :to="`/s/${storyId}/${reader.chapter.previousIndex}`"
            class="flex-1 rounded-lg border border-slate-300 py-3 text-center text-sm font-medium transition-colors hover:border-amber-500 dark:border-slate-700"
          >
            ‹ Previous
          </RouterLink>
          <RouterLink
            v-if="reader.chapter.nextIndex !== null"
            :to="`/s/${storyId}/${reader.chapter.nextIndex}`"
            class="flex-1 rounded-lg bg-amber-600 py-3 text-center text-sm font-semibold text-white transition-colors hover:bg-amber-500"
          >
            Next ›
          </RouterLink>
          <RouterLink
            v-else
            :to="`/s/${storyId}`"
            class="flex-1 rounded-lg border border-slate-300 py-3 text-center text-sm font-medium transition-colors hover:border-amber-500 dark:border-slate-700"
          >
            All chapters
          </RouterLink>
        </nav>

        <CommentSection
          :story-id="storyId"
          :chapter-index="chapterIndex"
          :story-author="reader.chapter.author"
        />
      </template>
    </main>
  </div>
</template>
