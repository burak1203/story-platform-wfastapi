<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useReaderStore } from '@/stores/readerStore'

const reader = useReaderStore()
const route = useRoute()

const storyId = computed(() => Number(route.params.id))

function load() {
  if (Number.isFinite(storyId.value)) reader.fetchStory(storyId.value)
}

onMounted(() => {
  load()
})
watch(storyId, load)

const firstChapter = computed(() => reader.story?.chapters[0]?.index ?? null)

function formatDate(value: string | null): string {
  if (!value) return ''
  return new Date(value).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}
</script>

<template>
  <div>
    <p v-if="reader.isLoading" class="py-16 text-center text-slate-500">Loading…</p>

    <div v-else-if="reader.notFound" class="py-16 text-center">
      <p class="text-lg font-semibold">Story not found</p>
      <p class="mt-2 text-sm text-slate-500 dark:text-slate-400">
        It may be private or no longer published.
      </p>
      <RouterLink to="/" class="mt-4 inline-block text-amber-600 underline dark:text-amber-500">
        Back to home
      </RouterLink>
    </div>

    <template v-else-if="reader.story">
      <h1 class="text-2xl font-bold leading-tight sm:text-3xl">{{ reader.story.title }}</h1>

      <div
        class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-slate-600 dark:text-slate-400"
      >
        <RouterLink
          :to="`/u/${reader.story.author}`"
          class="font-medium text-amber-600 hover:underline dark:text-amber-500"
        >
          {{ reader.story.author }}
        </RouterLink>
        <span>{{ reader.story.chapterCount }} chapters</span>
        <span>♥ {{ reader.story.likeCount }}</span>
        <span v-if="reader.story.publishedAt">{{ formatDate(reader.story.publishedAt) }}</span>
      </div>

      <!-- unlisted: linki bilen okuyabilir; okuru bu durumdan haberdar et -->
      <p
        v-if="reader.story.visibility === 'unlisted'"
        class="mt-3 rounded-lg bg-slate-200 px-3 py-2 text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-300"
      >
        Unlisted — only people with the link can find this story.
      </p>

      <!-- Kullanici icerigi: v-html YOK, pre-wrap ile metin -->
      <p
        v-if="reader.story.description"
        class="mt-4 whitespace-pre-wrap text-[15px] leading-relaxed text-slate-700 dark:text-slate-300"
      >
        {{ reader.story.description }}
      </p>

      <div v-if="reader.story.tags.length" class="mt-4 flex flex-wrap gap-2">
        <RouterLink
          v-for="tag in reader.story.tags"
          :key="tag"
          :to="{ path: '/', query: { tag } }"
          class="rounded-full bg-slate-200 px-3 py-1 text-xs text-slate-700 transition-colors hover:bg-amber-100 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-amber-500/15"
          >#{{ tag }}</RouterLink
        >
      </div>

      <RouterLink
        v-if="firstChapter !== null"
        :to="`/s/${reader.story.id}/${firstChapter}`"
        class="mt-6 block rounded-lg bg-amber-600 py-3 text-center font-semibold text-white transition-colors hover:bg-amber-500"
      >
        Start reading
      </RouterLink>

      <h2 class="mt-8 text-lg font-semibold">Chapters</h2>
      <p v-if="!reader.story.chapters.length" class="mt-2 text-sm text-slate-500">
        No chapters yet.
      </p>
      <ul
        v-else
        class="mt-3 divide-y divide-slate-200 overflow-hidden rounded-xl border border-slate-200 dark:divide-slate-800 dark:border-slate-800"
      >
        <li v-for="chapter in reader.story.chapters" :key="chapter.index">
          <RouterLink
            :to="`/s/${reader.story.id}/${chapter.index}`"
            class="flex items-center gap-3 bg-white px-4 py-3 transition-colors hover:bg-amber-50 dark:bg-slate-800/50 dark:hover:bg-slate-800"
          >
            <span class="font-medium">Chapter {{ chapter.index }}</span>
            <span class="ml-auto whitespace-nowrap text-xs text-slate-500 dark:text-slate-400">
              ♥ {{ chapter.likeCount }} · 💬 {{ chapter.commentCount }}
            </span>
          </RouterLink>
        </li>
      </ul>
    </template>
  </div>
</template>
