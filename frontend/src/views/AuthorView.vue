<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useReaderStore } from '@/stores/readerStore'
import SiteHeader from '@/components/SiteHeader.vue'
import StoryCard from '@/components/StoryCard.vue'

const reader = useReaderStore()
const route = useRoute()

const username = computed(() => String(route.params.username || ''))

function load() {
  if (username.value) reader.fetchProfile(username.value)
}

onMounted(() => {
  load()
})
watch(username, load)

function formatDate(value: string): string {
  return new Date(value + (value.endsWith('Z') ? '' : 'Z')).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'long',
  })
}
</script>

<template>
  <div class="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-900 dark:text-slate-100">
    <SiteHeader />

    <main class="mx-auto max-w-5xl px-4 py-6">
      <p v-if="reader.isLoading" class="py-16 text-center text-slate-500">Loading…</p>

      <div v-else-if="reader.notFound" class="py-16 text-center">
        <p class="text-lg font-semibold">Author not found</p>
        <RouterLink to="/" class="mt-4 inline-block text-amber-600 underline dark:text-amber-500">
          Back to home
        </RouterLink>
      </div>

      <template v-else-if="reader.profile">
        <h1 class="text-2xl font-bold sm:text-3xl">{{ reader.profile.username }}</h1>
        <div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-600 dark:text-slate-400">
          <span>♥ {{ reader.profile.totalLikes }} total likes</span>
          <span>{{ reader.profile.stories.length }} published</span>
          <span>Joined {{ formatDate(reader.profile.joinedAt) }}</span>
        </div>

        <h2 class="mt-8 text-lg font-semibold">Stories</h2>
        <p v-if="!reader.profile.stories.length" class="mt-2 text-sm text-slate-500 dark:text-slate-400">
          This author has not published any stories yet.
        </p>
        <div v-else class="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <StoryCard v-for="story in reader.profile.stories" :key="story.id" :story="story" />
        </div>
      </template>
    </main>
  </div>
</template>
