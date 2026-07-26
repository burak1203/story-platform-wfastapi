import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'

import StudioView from '@/views/StudioView.vue'
import LoginView from '@/views/LoginView.vue'
import RegisterView from '@/views/RegisterView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: LoginView,
      meta: { requiresGuest: true },
    },
    {
      path: '/register',
      name: 'register',
      component: RegisterView,
      meta: { requiresGuest: true },
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('@/views/DashboardView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/studio/:id',
      name: 'studio',
      component: StudioView,
      meta: { requiresAuth: true },
    },
    // --- Okuyucu platformu (PUBLIC) ---
    // Bu rotalarda requiresAuth/requiresGuest meta'si YOKTUR; asagidaki guard yalnizca o
    // iki meta'ya bakar, dolayisiyla public rotalar dogal olarak guard'in DISINDA kalir.
    // Buraya requiresAuth eklenirse girissiz okuma kirilir.
    {
      path: '/',
      name: 'home',
      component: () => import('@/views/HomeView.vue'),
    },
    {
      path: '/s/:id',
      name: 'story',
      component: () => import('@/views/StoryView.vue'),
    },
    {
      path: '/s/:id/:index',
      name: 'read',
      component: () => import('@/views/ReadView.vue'),
    },
    {
      path: '/u/:username',
      name: 'author',
      component: () => import('@/views/AuthorView.vue'),
    },
  ],

  // Okuma sayfasinda geri tusuna basinca okur kaldigi yere donmeli; yeni sayfada basa git.
  scrollBehavior(to, from, savedPosition) {
    return savedPosition || { top: 0 }
  },
})

// Trafik Polisi (Route Guard)
router.beforeEach((to, from, next) => {
  const authStore = useAuthStore()

  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    // Girisden sonra kullaniciyi gitmek istedigi yere geri gonder
    next({ path: '/login', query: { redirect: to.fullPath } })
  } else if (to.meta.requiresGuest && authStore.isAuthenticated) {
    next('/dashboard')
  } else {
    next()
  }
})

// main.ts'nin aradığı ve bulamadığı o kilit satır:
export default router
