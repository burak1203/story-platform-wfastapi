<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useReaderStore } from '@/stores/readerStore'
import SiteHeader from '@/components/SiteHeader.vue'
import StoryCard from '@/components/StoryCard.vue'

const reader = useReaderStore()
const route = useRoute()
const router = useRouter()

// Arama ve etiket URL'de tutulur: paylasilabilir ve geri tusuyla gezilebilir olsun.
const queryInput = ref((route.query.q as string) || '')

function activeQuery() {
  return {
    q: (route.query.q as string) || '',
    tag: (route.query.tag as string) || '',
  }
}

function load() {
  reader.fetchStories(activeQuery())
}

function submitSearch() {
  // Etiket filtresi aramaya RAGMEN korunur (ikisi birlikte daraltir)
  const query: Record<string, string> = {}
  const q = queryInput.value.trim()
  const { tag } = activeQuery()
  if (q) query.q = q
  if (tag) query.tag = tag
  router.push({ path: '/', query })
}

function clearFilters() {
  queryInput.value = ''
  router.push({ path: '/' })
}

onMounted(() => {
  load()
})

// URL degisince (arama, etiket, geri tusu) listeyi tazele
watch(() => route.query, () => {
  queryInput.value = (route.query.q as string) || ''
  load()
})
</script>

<template>
  <div class="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-900 dark:text-slate-100">
    <SiteHeader />

    <main class="mx-auto max-w-5xl px-4 py-6">
      <h1 class="text-xl font-bold sm:text-2xl">Latest stories</h1>
      <p class="mt-1 text-sm text-slate-600 dark:text-slate-400">
        Interactive fiction with chapter memory.
      </p>

      <!-- Arama: 375px'te tam genislik, sm'den itibaren buton yan yana -->
      <form @submit.prevent="submitSearch" class="mt-4 flex flex-col gap-2 sm:flex-row">
        <input
          v-model="queryInput"
          type="search"
          placeholder="Search titles and descriptions"
          maxlength="200"
          class="w-full rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-base outline-none transition-colors placeholder:text-slate-400 focus:border-amber-500 dark:border-slate-700 dark:bg-slate-800 dark:placeholder:text-slate-500"
        />
        <button
          type="submit"
          class="rounded-lg bg-amber-600 px-5 py-2.5 font-semibold text-white transition-colors hover:bg-amber-500 sm:w-auto"
        >
          Search
        </button>
      </form>

      <!-- Etkin filtreler -->
      <div
        v-if="route.query.q || route.query.tag"
        class="mt-3 flex flex-wrap items-center gap-2 text-sm"
      >
        <span v-if="route.query.tag" class="rounded-full bg-amber-100 px-3 py-1 text-amber-800 dark:bg-amber-500/15 dark:text-amber-400">
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

      <p v-if="reader.error" class="mt-6 rounded-lg bg-red-100 p-3 text-sm text-red-800 dark:bg-red-900/40 dark:text-red-200">
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
    </main>
  </div>
</template>
