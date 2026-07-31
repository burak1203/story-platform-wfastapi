import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { routes } from './routes'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,

  // Okuma sayfasinda geri tusuna basinca okur kaldigi yere donmeli; yeni sayfada basa git.
  scrollBehavior(to, from, savedPosition) {
    return savedPosition || { top: 0 }
  },
})

// Trafik Polisi (Route Guard)
// vue-router 5'te next() DEPRECATED (her gezinmede konsola uyari basiyordu); deger
// DONDURULUR: hedef = yonlendir, true = devam.
router.beforeEach((to) => {
  const authStore = useAuthStore()

  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    // Girisden sonra kullaniciyi gitmek istedigi yere geri gonder. Bu degeri OKUYAN
    // taraf onu safeRedirect'ten gecirir (bkz. router/redirect.ts) — ham kullanilmaz.
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.meta.requiresGuest && authStore.isAuthenticated) {
    return { path: '/dashboard' }
  }
  return true
})

// main.ts'nin aradığı ve bulamadığı o kilit satır:
export default router
