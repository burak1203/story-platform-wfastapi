<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { useAuthStore } from '@/stores/authStore'

// Sunucuda GOOGLE_OAUTH_CLIENT_ID tanimli degilse buton hic gorunmez
const enabled = ref(false)
const container = ref<HTMLElement | null>(null)
const router = useRouter()
const authStore = useAuthStore()

const GSI_SRC = 'https://accounts.google.com/gsi/client'

function loadGsiScript(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${GSI_SRC}"]`)) return resolve()
    const script = document.createElement('script')
    script.src = GSI_SRC
    script.async = true
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('Google girişi yüklenemedi'))
    document.head.appendChild(script)
  })
}

async function onCredential(response: { credential: string }) {
  try {
    await authStore.googleLogin(response.credential)
    router.push('/dashboard')
  } catch {
    // Hata authStore.error uzerinden ekranda gosterilir
  }
}

onMounted(async () => {
  try {
    const { data } = await axios.get('/api/auth/google-config')
    if (!data.clientId) return
    await loadGsiScript()
    const google = (window as any).google
    if (!google?.accounts?.id || !container.value) return
    google.accounts.id.initialize({ client_id: data.clientId, callback: onCredential })
    google.accounts.id.renderButton(container.value, {
      theme: 'filled_black',
      size: 'large',
      width: 320,
      text: 'continue_with',
    })
    enabled.value = true
  } catch {
    // Google erisilemiyorsa sessizce e-posta/sifre girisine dus
  }
})
</script>

<template>
  <div v-show="enabled" class="mt-6">
    <div class="flex items-center gap-3 mb-4">
      <div class="flex-1 h-px bg-slate-700"></div>
      <span class="text-xs text-slate-500">veya</span>
      <div class="flex-1 h-px bg-slate-700"></div>
    </div>
    <div ref="container" class="flex justify-center"></div>
  </div>
</template>
