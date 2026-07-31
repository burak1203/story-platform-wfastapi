import 'vue-router'

// Route meta'sini TIPLI hale getirir: `route.meta.width` aksi halde `unknown` doner ve
// kabuk icinde her kullanimda cast gerekir. Yeni bir meta alani eklendiginde burasi da
// guncellenir — boylece yazim hatasi derlemede yakalanir.
declare module 'vue-router' {
  interface RouteMeta {
    /** Guard: giris zorunlu. */
    requiresAuth?: boolean
    /** Guard: yalnizca girissiz kullanici (login/register). */
    requiresGuest?: boolean
    /** ReaderLayout icerik genisligi. Kabuk sabit genislik DAYATMAZ. */
    width?: 'wide' | 'narrow'
  }
}
