<script setup lang="ts">
import { RouterLink } from 'vue-router'
import type { PublicStoryCard } from '@/types'

defineProps<{ story: PublicStoryCard }>()
</script>

<template>
  <RouterLink
    :to="`/s/${story.id}`"
    class="flex flex-col gap-2 rounded-xl border border-slate-200 bg-white p-4 transition-colors hover:border-amber-500 dark:border-slate-800 dark:bg-slate-800/50 dark:hover:border-amber-500"
  >
    <h3 class="text-base font-semibold leading-snug text-slate-900 dark:text-slate-100">
      {{ story.title }}
    </h3>

    <!-- Aciklama LLM/kullanici icerigi: v-html YOK, metin olarak. line-clamp ile 3 satir -->
    <p
      v-if="story.description"
      class="line-clamp-3 whitespace-pre-wrap text-sm leading-relaxed text-slate-600 dark:text-slate-400"
    >{{ story.description }}</p>

    <div v-if="story.tags.length" class="flex flex-wrap gap-1.5">
      <span
        v-for="tag in story.tags"
        :key="tag"
        class="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600 dark:bg-slate-700 dark:text-slate-300"
      >{{ tag }}</span>
    </div>

    <div
      class="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 pt-1 text-xs text-slate-500 dark:text-slate-400"
    >
      <span class="font-medium text-slate-700 dark:text-slate-300">{{ story.author }}</span>
      <span>{{ story.chapterCount }} {{ story.chapterCount === 1 ? 'chapter' : 'chapters' }}</span>
      <span>♥ {{ story.likeCount }}</span>
    </div>
  </RouterLink>
</template>
