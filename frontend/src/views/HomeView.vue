<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useReaderStore } from '@/stores/readerStore'
import StoryCard from '@/components/StoryCard.vue'

const reader = useReaderStore()
const route = useRoute()
const router = useRouter()

function activeQuery() {
  return {
    q: (route.query.q as string) || '',
    tag: (route.query.tag as string) || '',
  }
}

function load() {
  reader.fetchStories(activeQuery())
}

function clearFilters() {
  router.push({ path: '/' })
}

onMounted(() => {
  load()
})

// URL degisince (arama, etiket, geri tusu) listeyi tazele. Arama kutusu kabukta
// (ReaderLayout header'i) — o da ayni URL query'sini yazar, yani ikisi senkron kalir.
watch(
  () => route.query,
  () => {
    load()
  },
)
</script>

<template>
  <div>
    <h1 class="text-xl font-bold sm:text-2xl">Latest stories</h1>
    <p class="mt-1 text-sm text-slate-600 dark:text-slate-400">
      Interactive fiction with chapter memory.
    </p>

    <!-- Etkin filtreler -->
    <div
      v-if="route.query.q || route.query.tag"
      class="mt-4 flex flex-wrap items-center gap-2 text-sm"
    >
      <span
        v-if="route.query.tag"
        class="rounded-full bg-amber-100 px-3 py-1 text-amber-800 dark:bg-amber-500/15 dark:text-amber-400"
      >
        #{{ route.query.tag }}
      </span>
      <span v-if="route.query.q" class="text-slate-600 dark:text-slate-400">
        Results for “{{ route.query.q }}”
      </span>
      <button
        type="button"
        @click="clearFilters"
        class="text-slate-500 underline transition-colors hover:text-amber-600 dark:text-slate-400"
      >
        Clear
      </button>
    </div>

    <p
      v-if="reader.error"
      class="mt-6 rounded-lg bg-red-100 p-3 text-sm text-red-800 dark:bg-red-900/40 dark:text-red-200"
    >
      {{ reader.error }}
    </p>

    <p v-if="reader.isLoading" class="mt-8 text-center text-slate-500">Loading…</p>

    <p
      v-else-if="!reader.cards.length"
      class="mt-10 text-center text-slate-500 dark:text-slate-400"
    >
      No stories published yet.
    </p>

    <!-- 375px: tek sutun. sm: 2, lg: 3 -->
    <div v-else class="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <StoryCard v-for="story in reader.cards" :key="story.id" :story="story" />
    </div>

    <div v-if="reader.hasMore && !reader.isLoading" class="mt-6 flex justify-center">
      <button
        type="button"
        @click="reader.fetchStories({ ...activeQuery(), append: true })"
        :disabled="reader.isLoadingMore"
        class="rounded-lg border border-slate-300 px-6 py-2.5 font-medium transition-colors hover:border-amber-500 disabled:opacity-50 dark:border-slate-700"
      >
        {{ reader.isLoadingMore ? 'Loading…' : 'Load more' }}
      </button>
    </div>
  </div>
</template>
