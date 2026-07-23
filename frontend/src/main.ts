import './assets/main.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import axios from 'axios'
import App from './App.vue'
import router from './router' // Router eklendi
import { useAuthStore } from './stores/authStore' // Auth store eklendi

const app = createApp(App)

app.use(createPinia())
app.use(router) // Router'ı Vue'ya bağlıyoruz

// Uygulama başlarken daha önceden kalan token varsa Axios'a ekle
const authStore = useAuthStore()
authStore.setAxiosHeader()

// BYOK: kullanıcının üretim ayarları (sağlayıcı + base URL + model + anahtar) yalnızca
// tarayıcıda durur, her isteğe header olarak eklenir. Sunucuda hiçbir varsayılan yok.
axios.interceptors.request.use((config) => {
  const key = localStorage.getItem('llm_api_key')
  if (key) {
    config.headers['X-LLM-API-Key'] = key
    config.headers['X-LLM-Base-URL'] = localStorage.getItem('llm_base_url') || ''
    config.headers['X-LLM-Model'] = localStorage.getItem('llm_model') || ''
    config.headers['X-LLM-Provider'] = localStorage.getItem('llm_provider') || ''
  }
  return config
})

app.mount('#app')
