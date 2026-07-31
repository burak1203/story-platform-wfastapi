<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <div class="py-20 text-center">
    <p class="text-sm font-semibold uppercase tracking-wide text-amber-600 dark:text-amber-500">
      404
    </p>
    <h1 class="mt-2 text-2xl font-bold sm:text-3xl">This page does not exist</h1>
    <p class="mt-3 text-sm text-slate-600 dark:text-slate-400">
      The link may be broken, or the story may have been unpublished.
    </p>
    <RouterLink
      to="/"
      class="mt-6 inline-block rounded-lg bg-amber-600 px-5 py-2.5 font-semibold text-white transition-colors hover:bg-amber-500"
    >
      Browse stories
    </RouterLink>
  </div>
</template>
