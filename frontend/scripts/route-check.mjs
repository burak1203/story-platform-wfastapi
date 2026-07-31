// Rota cozumleme + acik yonlendirme testi.  Calistir:  npm run route-check
//
// Bu test KOPYA degil GERCEK kodu kullanir: rota tablosunu src/router/routes.ts'ten,
// safeRedirect'i src/router/redirect.ts'ten import eder. Node .ts dosyalarini dogrudan
// yukleyebiliyor; routes.ts'te ust seviye .vue importu YOK (hepsi tembel) ve
// createWebHistory orada cagrilmiyor, bu yuzden tarayici gerekmiyor.
import { createRouter, createMemoryHistory } from 'vue-router'
import { routes } from '../src/router/routes.ts'
import { safeRedirect } from '../src/router/redirect.ts'

const router = createRouter({ history: createMemoryHistory(), routes })

let failed = 0
function check(label, actual, expected) {
  const ok = actual === expected
  if (!ok) failed++
  console.log(`  ${ok ? 'OK  ' : 'HATA'} ${label.padEnd(34)} ${ok ? '' : `${actual} != ${expected}`}`)
}

// --- 1) Rota cozumleme: dogru isim + dogru kabuk ---
// Kabuk, eslesen zincirin ILK kaydinin dosya yolundan okunur (tembel import fonksiyonunun
// kaynagindan). Boylece "hangi layout'a dustu" sorusunu bilesen ornegine ihtiyac duymadan
// yanitliyoruz.
function shellOf(resolved) {
  const top = resolved.matched[0]
  if (!top || top.name) return 'KABUKSUZ' // isimli ust kayit = layout'suz rota
  const src = String(top.components?.default ?? '')
  if (src.includes('ReaderLayout')) return 'Reader'
  if (src.includes('StudioLayout')) return 'Studio'
  return '?'
}

console.log('\n[1] Rota cozumleme')
const routeCases = [
  ['/', 'home', 'Reader'],
  ['/s/12', 'story', 'Reader'],
  ['/u/ali', 'author', 'Reader'],
  ['/s/12/3', 'read', 'KABUKSUZ'],
  ['/login', 'login', 'KABUKSUZ'],
  ['/register', 'register', 'KABUKSUZ'],
  ['/dashboard', 'dashboard', 'Studio'],
  ['/studio/7', 'studio', 'Studio'],
  ['/settings', 'settings', 'Studio'],
  // 404 yakalayici: YALNIZCA tanimsiz yollari yakalamali
  ['/boyle-bir-sey-yok', 'not-found', 'Reader'],
  ['/a/b/c/d', 'not-found', 'Reader'],
]
for (const [path, expectedName, expectedShell] of routeCases) {
  const r = router.resolve(path)
  check(`${path} -> isim`, String(r.name), expectedName)
  check(`${path} -> kabuk`, shellOf(r), expectedShell)
}

// --- 2) Rota meta'si (ReaderLayout genisligi buradan okuyor) ---
console.log('\n[2] Meta')
check('/ genislik', router.resolve('/').meta.width, 'wide')
check('/s/12 genislik', router.resolve('/s/12').meta.width, 'narrow')
check('/dashboard requiresAuth', router.resolve('/dashboard').meta.requiresAuth, true)
check('/studio/7 requiresAuth', router.resolve('/studio/7').meta.requiresAuth, true)
check('/settings requiresAuth', router.resolve('/settings').meta.requiresAuth, true)
check('/login requiresGuest', router.resolve('/login').meta.requiresGuest, true)
// Public okuma rotalari guard'in DISINDA kalmali
check('/ requiresAuth yok', router.resolve('/').meta.requiresAuth, undefined)
check('/s/12/3 requiresAuth yok', router.resolve('/s/12/3').meta.requiresAuth, undefined)

// --- 3) Acik yonlendirme (open redirect) ---
console.log('\n[3] safeRedirect')
const DEFAULT = '/dashboard'
const redirectCases = [
  // Kabul edilenler: tek "/" ile baslayan goreli yollar
  ['/studio/3', '/studio/3'],
  ['/s/1/2?x=1', '/s/1/2?x=1'],
  ['/', '/'],
  // Reddedilenler: uygulama disina cikaran her sey
  ['//evil.com', DEFAULT],
  ['///evil.com', DEFAULT],
  ['/\\evil.com', DEFAULT],
  ['http://evil.com', DEFAULT],
  ['https://evil.com', DEFAULT],
  ['javascript:alert(1)', DEFAULT],
  ['evil.com', DEFAULT],
  // Kontrol karakteri kacamagi: tarayici TAB/LF/CR'yi adresten siler, yani bunlar
  // temizlenmeden once "//" kontrolunu atlatiyorlardi.
  ['/\t/evil.com', DEFAULT],
  ['/\n/evil.com', DEFAULT],
  ['/\r/evil.com', DEFAULT],
  ['/\t\\evil.com', DEFAULT],
  // Tip kacamaklari
  [undefined, DEFAULT],
  [null, DEFAULT],
  [['/a', '/b'], DEFAULT], // ?redirect=a&redirect=b dizi doner
  [42, DEFAULT],
]
for (const [input, expected] of redirectCases) {
  check(`safeRedirect(${JSON.stringify(input)})`, safeRedirect(input), expected)
}

console.log(failed === 0 ? '\nTUMU GECTI\n' : `\n${failed} KONTROL BASARISIZ\n`)
process.exit(failed === 0 ? 0 : 1)
