<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { safeRedirect } from '@/router/redirect'
import GoogleSignInButton from '@/components/GoogleSignInButton.vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const username = ref('')
const email = ref('')
const password = ref('')

const handleRegister = async () => {
  if (!username.value || !email.value || !password.value) return

  try {
    await authStore.register({
      username: username.value,
      email: email.value,
      password: password.value,
    })
    // Okuyucu tarafindan yonlendirildiyse geldigi yere don
    router.push(safeRedirect(route.query.redirect))
  } catch (error) {
    // Hata store'dan okunuyor
  }
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-slate-900 text-gray-200">
    <div class="bg-slate-800 p-8 rounded-xl shadow-2xl w-full max-w-md border border-slate-700">
      <h1 class="text-2xl font-bold text-amber-500 mb-6 text-center">Yeni Serüven Başlat</h1>

      <div
        v-if="authStore.error"
        class="bg-red-900/50 border border-red-500 text-red-200 p-3 mb-6 rounded text-sm"
      >
        {{ authStore.error }}
      </div>

      <form @submit.prevent="handleRegister" class="flex flex-col gap-4">
        <div>
          <label class="block text-sm font-medium text-slate-400 mb-1"
            >Kullanıcı Adı <span class="text-slate-500">(en az 3 karakter)</span></label
          >
          <input
            v-model="username"
            type="text"
            minlength="3"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-3 text-gray-100 focus:outline-none focus:border-amber-500 transition-colors"
            required
          />
        </div>

        <div>
          <label class="block text-sm font-medium text-slate-400 mb-1">E-posta</label>
          <input
            v-model="email"
            type="email"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-3 text-gray-100 focus:outline-none focus:border-amber-500 transition-colors"
            required
          />
        </div>

        <div>
          <label class="block text-sm font-medium text-slate-400 mb-1"
            >Şifre <span class="text-slate-500">(en az 6 karakter)</span></label
          >
          <input
            v-model="password"
            type="password"
            minlength="6"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-3 text-gray-100 focus:outline-none focus:border-amber-500 transition-colors"
            required
          />
        </div>

        <button
          type="submit"
          class="w-full bg-emerald-600 hover:bg-emerald-500 text-slate-900 font-bold py-3 rounded-lg transition-colors mt-4"
          :disabled="authStore.isLoading"
        >
          {{ authStore.isLoading ? 'Kayıt Olunuyor...' : 'Kayıt Ol' }}
        </button>
      </form>

      <GoogleSignInButton />

      <div class="mt-6 text-center text-sm text-slate-400">
        Zaten hesabın var mı?
        <RouterLink
          :to="{ path: '/login', query: route.query.redirect ? { redirect: route.query.redirect } : {} }"
          class="text-amber-500 hover:underline"
        >Giriş Yap</RouterLink>
      </div>
    </div>
  </div>
</template>
