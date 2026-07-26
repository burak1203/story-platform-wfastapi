<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { useReaderStore, COMMENT_PAGE_SIZE } from '@/stores/readerStore'

const props = defineProps<{ storyId: number; chapterIndex: number; storyAuthor: string }>()

const reader = useReaderStore()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const MAX_LEN = 2000

const draft = ref('')
const isSending = ref(false)
const localError = ref<string | null>(null)

// Hikayenin yazari MIYIM: sabitleme ve moderasyon dugmeleri bunun icin.
// Sadece GORUNURLUK; sunucu ayrica dogruluyor.
const isStoryAuthor = computed(
  () => auth.isAuthenticated && auth.username === props.storyAuthor,
)

function canDelete(commentAuthor: string): boolean {
  return auth.isAuthenticated && (auth.username === commentAuthor || isStoryAuthor.value)
}

/** Girissiz kullanici: HATA degil, giris sayfasina YONLENDIRME (donusu icin redirect ile). */
function goToLogin() {
  router.push({ path: '/login', query: { redirect: route.fullPath } })
}

async function submit() {
  if (!auth.isAuthenticated) return goToLogin()
  const body = draft.value.trim()
  if (!body) return

  isSending.value = true
  localError.value = null
  try {
    await reader.addComment(props.storyId, props.chapterIndex, body)
    draft.value = ''
  } catch (err: any) {
    localError.value =
      err?.response?.status === 429
        ? 'You are commenting too fast. Please wait a moment.'
        : err?.response?.data?.detail || 'Your comment could not be posted.'
  } finally {
    isSending.value = false
  }
}

async function remove(commentId: number) {
  if (!confirm('Delete this comment?')) return
  try {
    await reader.deleteComment(props.storyId, props.chapterIndex, commentId)
  } catch {
    localError.value = 'The comment could not be deleted.'
  }
}

async function togglePin(commentId: number, pinned: boolean) {
  try {
    await reader.pinComment(props.storyId, props.chapterIndex, commentId, pinned)
  } catch {
    localError.value = 'The comment could not be pinned.'
  }
}

function formatDate(value: string): string {
  return new Date(value + (value.endsWith('Z') ? '' : 'Z')).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

const hasMore = computed(() => reader.comments.length < reader.commentTotal)
</script>

<template>
  <section class="mt-10 border-t border-slate-200 pt-6 dark:border-slate-800">
    <h2 class="text-lg font-semibold">
      Comments <span class="text-slate-500">({{ reader.commentTotal }})</span>
    </h2>

    <!-- Yazma alani -->
    <div class="mt-4">
      <template v-if="auth.isAuthenticated">
        <textarea
          v-model="draft"
          rows="3"
          :maxlength="MAX_LEN"
          placeholder="Share your thoughts on this chapter…"
          class="w-full resize-y rounded-lg border border-slate-300 bg-white px-3 py-2 text-[15px] leading-relaxed outline-none transition-colors placeholder:text-slate-400 focus:border-amber-500 dark:border-slate-700 dark:bg-slate-800 dark:placeholder:text-slate-500"
        ></textarea>
        <div class="mt-2 flex items-center gap-3">
          <button
            type="button"
            @click="submit"
            :disabled="isSending || !draft.trim()"
            class="rounded-lg bg-amber-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-amber-500 disabled:opacity-50"
          >
            {{ isSending ? 'Posting…' : 'Post comment' }}
          </button>
          <span class="text-xs text-slate-500">{{ draft.length }}/{{ MAX_LEN }}</span>
        </div>
      </template>

      <button
        v-else
        type="button"
        @click="goToLogin"
        class="w-full rounded-lg border border-dashed border-slate-300 py-3 text-sm text-slate-600 transition-colors hover:border-amber-500 hover:text-amber-600 dark:border-slate-700 dark:text-slate-400"
      >
        Sign in to leave a comment
      </button>
    </div>

    <p
      v-if="localError"
      class="mt-3 rounded-lg bg-red-100 p-3 text-sm text-red-800 dark:bg-red-900/40 dark:text-red-200"
    >
      {{ localError }}
    </p>

    <!-- Liste: sabitlenenler ustte (sira sunucudan gelir) -->
    <p v-if="!reader.comments.length" class="mt-6 text-sm text-slate-500 dark:text-slate-400">
      No comments yet.
    </p>

    <ul v-else class="mt-6 flex flex-col gap-4">
      <li
        v-for="comment in reader.comments"
        :key="comment.id"
        class="rounded-xl border p-3"
        :class="
          comment.isPinned
            ? 'border-amber-400 bg-amber-50 dark:border-amber-500/40 dark:bg-amber-500/10'
            : 'border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-800/50'
        "
      >
        <div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
          <RouterLink
            :to="`/u/${comment.author}`"
            class="font-semibold text-slate-800 hover:underline dark:text-slate-200"
          >{{ comment.author }}</RouterLink>

          <span
            v-if="comment.isAuthor"
            class="rounded-full bg-amber-600 px-2 py-0.5 font-medium text-white"
          >Author</span>
          <span v-if="comment.isPinned" class="text-amber-700 dark:text-amber-400">📌 Pinned</span>

          <span class="text-slate-500 dark:text-slate-400">{{ formatDate(comment.createdAt) }}</span>
        </div>

        <!-- KULLANICI ICERIGI: v-html YOK. pre-wrap satir sonlarini korur, break-words
             bosluksuz uzun metnin 375px'te tasmasini onler. -->
        <p
          class="mt-2 whitespace-pre-wrap break-words text-[15px] leading-relaxed text-slate-800 dark:text-slate-200"
        >{{ comment.body }}</p>

        <div
          v-if="canDelete(comment.author) || isStoryAuthor"
          class="mt-2 flex gap-3 text-xs text-slate-500"
        >
          <button
            v-if="isStoryAuthor"
            type="button"
            @click="togglePin(comment.id, !comment.isPinned)"
            class="transition-colors hover:text-amber-600"
          >
            {{ comment.isPinned ? 'Unpin' : 'Pin' }}
          </button>
          <button
            v-if="canDelete(comment.author)"
            type="button"
            @click="remove(comment.id)"
            class="transition-colors hover:text-red-600"
          >
            Delete
          </button>
        </div>
      </li>
    </ul>

    <button
      v-if="hasMore"
      type="button"
      @click="reader.fetchComments(props.storyId, props.chapterIndex, true)"
      class="mt-4 w-full rounded-lg border border-slate-300 py-2 text-sm transition-colors hover:border-amber-500 dark:border-slate-700"
    >
      Load {{ Math.min(COMMENT_PAGE_SIZE, reader.commentTotal - reader.comments.length) }} more
    </button>
  </section>
</template>
