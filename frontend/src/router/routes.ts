import type { RouteRecordRaw } from 'vue-router'

// Rota TABLOSU router ornegiden AYRI durur. Sebep: tablo boylece tarayici gerektirmeden
// import edilebiliyor ve scripts/route-check.mjs GERCEK tabloyu test ediyor — kopyasini
// degil. (index.ts createWebHistory cagirdigi icin node'da yuklenemez.)
//
// Bu yuzden buradaki TUM bilesenler TEMBEL (`() => import(...)`): ust seviye .vue importu
// olsaydi node dosyayi yukleyemezdi. router.resolve() tembel yukleyicileri CAGIRMAZ.
//
// Rotalar UC gruba ayrilir:
//   1) Reader kabugu   — header'li, girissiz gezilebilir
//   2) Studio kabugu   — sidebar'li, yazar
//   3) KABUKSUZ        — kendi tam ekran duzeni olanlar (okuma, giris, kayit).
//      Bu grup icin bos bir layout bileseni YOK; dogrudan render olurlar.
export const routes: RouteRecordRaw[] = [
  // --- 3) KABUKSUZ ---
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { requiresGuest: true },
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/views/RegisterView.vue'),
    meta: { requiresGuest: true },
  },
  {
    // Okuma sayfasi: kendi ince cubugu var, kabuga sokmak cift baslik uretir.
    path: '/s/:id/:index',
    name: 'read',
    component: () => import('@/views/ReadView.vue'),
  },

  // --- 1) Reader kabugu (PUBLIC) ---
  // Bu rotalarda requiresAuth/requiresGuest meta'si YOKTUR; guard yalnizca o iki meta'ya
  // bakar, dolayisiyla public rotalar dogal olarak guard'in DISINDA kalir. Buraya
  // requiresAuth eklenirse girissiz okuma kirilir.
  {
    path: '/',
    component: () => import('@/layouts/ReaderLayout.vue'),
    children: [
      {
        path: '',
        name: 'home',
        component: () => import('@/views/HomeView.vue'),
        meta: { width: 'wide' },
      },
      {
        path: 's/:id',
        name: 'story',
        component: () => import('@/views/StoryView.vue'),
        meta: { width: 'narrow' },
      },
      {
        path: 'u/:username',
        name: 'author',
        component: () => import('@/views/AuthorView.vue'),
        meta: { width: 'wide' },
      },
      {
        // Tanimsiz yol Reader kabugunda anlamli bir sayfaya duser (header'li, geri
        // donus baglantili). Yakalayici olmasina ragmen mevcut rotalari GOLGELEMEZ:
        // vue-router statik/parametreli yollara yakalayicidan yuksek puan verir.
        // Bunu varsaymiyoruz — scripts/route-check.mjs bu iddiayi test ediyor.
        path: ':pathMatch(.*)*',
        name: 'not-found',
        component: () => import('@/views/NotFoundView.vue'),
        meta: { width: 'narrow' },
      },
    ],
  },

  // --- 2) Studio kabugu ---
  // SIRA YUK TASIYOR: bu grup Reader grubundan SONRA gelmeli. Iki parent da '/' yolunu
  // paylasiyor; Reader'in '' cocugu var, bu grubun yok. Studio once yazilirsa bare '/'
  // once buraya duser, hicbir cocuk eslesmez ve ana sayfa isimsiz/bos render olur.
  {
    path: '/',
    component: () => import('@/layouts/StudioLayout.vue'),
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: 'studio/:id',
        name: 'studio',
        component: () => import('@/views/StudioView.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/SettingsView.vue'),
        meta: { requiresAuth: true },
      },
    ],
  },
]
