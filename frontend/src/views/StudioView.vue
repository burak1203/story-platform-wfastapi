<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useStoryStore } from '@/stores/storyStore'
import { useLlmKeyStore } from '@/stores/llmKeyStore'
import type { ElementDto, ElementKind, PromptItemDto, PromptItemKind, Visibility } from '@/types'

const store = useStoryStore()
const llmKeyStore = useLlmKeyStore()
const route = useRoute()
const userAction = ref('')
const scrollContainer = ref<HTMLElement | null>(null)

const storyId = computed(() => Number(route.params.id))

// --- Bölüm düzenleme ---
const editingChapterIndex = ref<number | null>(null)
const chapterDraft = ref('')

// --- Özet düzenleme ---
const editingSummaryIndex = ref<number | null>(null)
const summaryDraft = ref('')

// --- Yazım ayarları: talimat MADDELERİ + son N bölüm ---
const showSettings = ref(false)
const newItemText = ref<Record<PromptItemKind, string>>({ style: '', negative: '' })
const editingItemId = ref<number | null>(null)
const itemDraft = ref('')
const lastChaptersDraft = ref(2)
const settingsSaved = ref(false)

const promptSections = computed(() => [
  {
    kind: 'style' as PromptItemKind,
    title: 'Talimatlar (her bölümde uygulanır)',
    placeholder: 'Örn: Karanlık ve şiirsel bir ton kullan',
    items: (store.story?.promptItems || []).filter((i) => i.kind === 'style'),
  },
  {
    kind: 'negative' as PromptItemKind,
    title: 'Negatif talimatlar (bunlardan kaçınılır)',
    placeholder: 'Örn: Modern teknolojiden bahsetme',
    items: (store.story?.promptItems || []).filter((i) => i.kind === 'negative'),
  },
])

// --- Varlık (karakter/mekan/eşya) düzenleme ---
const editingElement = ref<{ kind: ElementKind; id: number } | null>(null)
const elementNameDraft = ref('')
const elementDescDraft = ref('')
const addingElementKind = ref<ElementKind | null>(null)
const newElementName = ref('')
const newElementDesc = ref('')

onMounted(() => {
  store.fetchStory(storyId.value)
})

onUnmounted(() => {
  store.disconnectStream()
})

// Hikaye yüklendiğinde ayar taslaklarını doldur
watch(
  () => store.story?.id,
  () => {
    lastChaptersDraft.value = store.story?.lastChaptersFullText ?? 2
  },
)

// Guvenlik: LLM/kullanici icerigi HTML olarak degil, her zaman duz metin olarak basilir
const chapters = computed(() => store.story?.chapters || [])

watch(
  () => store.story?.content,
  async () => {
    await nextTick()
    if (scrollContainer.value && editingChapterIndex.value === null) {
      scrollContainer.value.scrollTop = scrollContainer.value.scrollHeight
    }
  },
)

const isBusy = computed(
  () => store.story?.status === 'PENDING' || store.story?.status === 'GENERATING',
)

const submitAction = async () => {
  if (!userAction.value.trim() || store.isLoading) return
  const actionText = userAction.value
  userAction.value = ''
  await store.continueStory(storyId.value, actionText)
}

// --- Bölüm ---
const startChapterEdit = (index: number, content: string) => {
  editingChapterIndex.value = index
  chapterDraft.value = content
}

const saveChapterEdit = async () => {
  if (editingChapterIndex.value === null || !chapterDraft.value.trim()) return
  await store.editChapter(storyId.value, editingChapterIndex.value, chapterDraft.value)
  editingChapterIndex.value = null
}

// --- Özet ---
const startSummaryEdit = (index: number, summary: string | null) => {
  editingSummaryIndex.value = index
  summaryDraft.value = summary || ''
}

const saveSummaryEdit = async () => {
  if (editingSummaryIndex.value === null) return
  await store.editChapterSummary(storyId.value, editingSummaryIndex.value, summaryDraft.value)
  editingSummaryIndex.value = null
}

// --- Ayarlar: talimat maddeleri ---
const addPromptItem = async (kind: PromptItemKind) => {
  const text = newItemText.value[kind].trim()
  if (!text) return
  await store.addPromptItem(storyId.value, kind, text)
  newItemText.value[kind] = ''
}

const startItemEdit = (item: PromptItemDto) => {
  editingItemId.value = item.id
  itemDraft.value = item.text
}

const saveItemEdit = async () => {
  if (editingItemId.value === null || !itemDraft.value.trim()) return
  await store.updatePromptItem(storyId.value, editingItemId.value, { text: itemDraft.value })
  editingItemId.value = null
}

const toggleItem = async (item: PromptItemDto) => {
  await store.updatePromptItem(storyId.value, item.id, { enabled: !item.enabled })
}

const removeItem = async (item: PromptItemDto) => {
  if (confirm('Bu talimatı silmek istediğine emin misin?')) {
    await store.deletePromptItem(storyId.value, item.id)
  }
}

/** Bir maddeyi kendi türü içinde yukarı/aşağı taşır. Sıra, promptta birleşme sırasıdır:
 *  kalıcı kurallar üstte, deneysel olanlar altta. */
const moveItem = async (kind: PromptItemKind, index: number, delta: number) => {
  const section = promptSections.value.find((s) => s.kind === kind)
  if (!section) return
  const target = index + delta
  if (target < 0 || target >= section.items.length) return
  const reordered = [...section.items]
  const [moved] = reordered.splice(index, 1)
  if (!moved) return
  reordered.splice(target, 0, moved)
  // Backend TÜM maddelerin sırasını bekler: diğer türü mevcut sırasıyla koru
  const others = (store.story?.promptItems || []).filter((i) => i.kind !== kind)
  const ids =
    kind === 'style'
      ? [...reordered.map((i) => i.id), ...others.map((i) => i.id)]
      : [...others.map((i) => i.id), ...reordered.map((i) => i.id)]
  await store.reorderPromptItems(storyId.value, ids)
}

const saveLastChapters = async () => {
  await store.updateSettings(storyId.value, lastChaptersDraft.value)
  settingsSaved.value = true
  setTimeout(() => (settingsSaved.value = false), 2000)
}

// --- Yayımlama (okuyucu platformu) ---
// F2.1'de uç eklendi ama arayüze bağlanmamıştı: yazar tarayıcıdan hikayesini
// yayımlayamıyordu, dolayısıyla okuyucu tarafı boş kalıyordu.
const showPublishing = ref(false)
const pubVisibility = ref<Visibility>('private')
const pubDescription = ref('')
const pubTags = ref('')
const pubIsAdult = ref(false)
const pubRulesAccepted = ref(false)
const pubSaved = ref(false)
const pubError = ref<string | null>(null)

// Hikaye yüklenince/değişince formu sunucudaki mevcut duruma eşitle
watch(
  () => store.story?.publishing,
  (publishing) => {
    if (!publishing) return
    pubVisibility.value = publishing.visibility
    pubDescription.value = publishing.description || ''
    pubTags.value = publishing.tags.join(', ')
    pubIsAdult.value = publishing.isAdult
    // Zaten yayındaysa kuralları daha önce onaylamış demektir
    pubRulesAccepted.value = publishing.visibility === 'public'
  },
  { immediate: true },
)

const publicUrl = computed(() =>
  store.story ? `${window.location.origin}/s/${store.story.id}` : '',
)

const savePublishing = async () => {
  pubError.value = null
  try {
    await store.updatePublishing(storyId.value, {
      visibility: pubVisibility.value,
      description: pubDescription.value.trim() || null,
      tags: pubTags.value
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean)
        .slice(0, 10),
      isAdult: pubIsAdult.value,
      rulesAccepted: pubRulesAccepted.value,
    })
    pubSaved.value = true
    setTimeout(() => (pubSaved.value = false), 2000)
  } catch (err: any) {
    pubError.value = err?.response?.data?.detail || 'Kaydedilemedi.'
  }
}

// --- Varlıklar ---
const startElementEdit = (kind: ElementKind, element: ElementDto) => {
  editingElement.value = { kind, id: element.id }
  elementNameDraft.value = element.name
  elementDescDraft.value = element.description
}

const saveElementEdit = async () => {
  if (!editingElement.value || !elementNameDraft.value.trim()) return
  await store.updateElement(
    editingElement.value.kind,
    storyId.value,
    editingElement.value.id,
    elementNameDraft.value,
    elementDescDraft.value,
  )
  editingElement.value = null
}

const removeElement = async (kind: ElementKind, id: number) => {
  if (confirm('Bu öğeyi silmek istediğine emin misin?')) {
    await store.deleteElement(kind, storyId.value, id)
  }
}

const saveNewElement = async () => {
  if (!addingElementKind.value || !newElementName.value.trim()) return
  await store.addElement(
    addingElementKind.value,
    storyId.value,
    newElementName.value,
    newElementDesc.value,
  )
  addingElementKind.value = null
  newElementName.value = ''
  newElementDesc.value = ''
}

const elementSections = computed(() => [
  {
    kind: 'characters' as ElementKind,
    title: 'Karakterler',
    color: 'text-amber-500',
    items: store.story?.characters || [],
  },
  {
    kind: 'locations' as ElementKind,
    title: 'Mekanlar',
    color: 'text-emerald-500',
    items: store.story?.locations || [],
  },
  {
    kind: 'items' as ElementKind,
    title: 'Eşyalar',
    color: 'text-cyan-500',
    items: store.story?.items || [],
  },
])
</script>

<template>
  <!-- Yukseklik kabuktan ARTAN alan kadar: duz h-screen mobilde kabugun 48px'lik ust
       cubugunun ustune 100vh bindiriyor, sayfanin tamami 48px kayiyor ve ikinci bir
       kaydirma cubugu cikiyordu. Masaustunde ust cubuk yok, orada tam 100vh dogru.
       NOT: Stüdyo bilinçli olarak koyu bir calisma yuzeyi — kabugun temasini takip
       etmiyor (bkz. bitis raporu). -->
  <div
    class="h-[calc(100vh-3rem)] lg:h-screen w-full bg-slate-900 text-gray-200 flex overflow-hidden font-sans"
  >
    <!-- SOL PANEL: Ayarlar ve Bölüm Özetleri -->
    <aside class="w-1/4 bg-slate-800 border-r border-slate-700 p-6 flex flex-col">
      <h1 class="text-2xl font-bold text-amber-500 mb-2">
        {{ store.story?.title || 'Yükleniyor...' }}
      </h1>
      <div class="flex items-center gap-2 mb-4 text-sm text-slate-400">
        <span class="bg-slate-700 px-2 py-1 rounded"
          >Durum: {{ store.story?.status || '...' }}</span
        >
        <span class="bg-slate-700 px-2 py-1 rounded"
          >Bölüm: {{ store.story?.actionCount || 0 }}</span
        >
        <button
          @click="llmKeyStore.openModal()"
          class="bg-slate-700 hover:bg-slate-600 px-2 py-1 rounded transition-colors"
          :class="{ 'text-amber-500': !llmKeyStore.hasKey }"
          title="Gemini API anahtarını yönet"
        >
          🔑
        </button>
      </div>

      <!-- Yazım Ayarları -->
      <!-- shrink-0 + baslikta shrink-0: panel acikken bolum ozetleri listesi tarafindan ezilmesin -->
      <div class="mb-4 border border-slate-700 rounded-lg flex flex-col min-h-0 shrink-0">
        <button
          @click="showSettings = !showSettings"
          class="w-full text-left px-4 py-2 text-sm font-semibold text-slate-300 hover:text-amber-500 transition-colors shrink-0"
        >
          ⚙️ Yazım Ayarları {{ showSettings ? '▾' : '▸' }}
        </button>
        <!-- Kendi kaydirmasi: madde sayisi artinca panel tasip kirpilmasin (sol panel
             overflow-hidden icinde; kaydirma olmadan asagidaki negatif talimatlara ulasilamiyor) -->
        <div
          v-if="showSettings"
          class="p-3 pt-0 flex flex-col gap-4 overflow-y-auto max-h-[55vh] min-h-0"
        >
          <!-- Talimat maddeleri: tek tek açılıp kapanır, sıralanır -->
          <div v-for="section in promptSections" :key="section.kind" class="flex flex-col gap-2">
            <label class="text-xs text-slate-500">{{ section.title }}</label>
            <p v-if="!section.items.length" class="text-xs text-slate-600 italic">
              Henüz talimat yok.
            </p>

            <div
              v-for="(item, index) in section.items"
              :key="item.id"
              class="bg-slate-900/60 border border-slate-700 rounded p-2 flex flex-col gap-1"
            >
              <template v-if="editingItemId !== item.id">
                <div class="flex items-start gap-2">
                  <input
                    type="checkbox"
                    :checked="item.enabled"
                    @change="toggleItem(item)"
                    class="mt-0.5 accent-amber-500 shrink-0"
                    :title="item.enabled ? 'Açık — prompta gider' : 'Kapalı — prompta girmez'"
                  />
                  <span
                    class="text-xs leading-relaxed flex-1 whitespace-pre-wrap"
                    :class="item.enabled ? 'text-slate-300' : 'text-slate-600 line-through'"
                    >{{ item.text }}</span
                  >
                </div>
                <div class="flex gap-2 justify-end text-xs text-slate-500">
                  <button
                    @click="moveItem(section.kind, index, -1)"
                    :disabled="index === 0"
                    class="hover:text-amber-500 disabled:opacity-30 disabled:hover:text-slate-500"
                    title="Yukarı taşı"
                  >
                    ↑
                  </button>
                  <button
                    @click="moveItem(section.kind, index, 1)"
                    :disabled="index === section.items.length - 1"
                    class="hover:text-amber-500 disabled:opacity-30 disabled:hover:text-slate-500"
                    title="Aşağı taşı"
                  >
                    ↓
                  </button>
                  <button @click="startItemEdit(item)" class="hover:text-amber-500">✎</button>
                  <button @click="removeItem(item)" class="hover:text-red-500">✕</button>
                </div>
              </template>

              <div v-else class="flex flex-col gap-2">
                <textarea
                  v-model="itemDraft"
                  rows="3"
                  class="bg-slate-900 border border-slate-600 rounded p-2 text-xs focus:outline-none focus:border-amber-500 resize-none"
                ></textarea>
                <div class="flex gap-2 justify-end">
                  <button
                    @click="editingItemId = null"
                    class="text-xs text-slate-400 hover:text-slate-200"
                  >
                    İptal
                  </button>
                  <button
                    @click="saveItemEdit"
                    class="text-xs bg-amber-600 hover:bg-amber-500 text-slate-900 font-bold px-3 py-1 rounded"
                  >
                    Kaydet
                  </button>
                </div>
              </div>
            </div>

            <div class="flex gap-2">
              <input
                v-model="newItemText[section.kind]"
                type="text"
                :placeholder="section.placeholder"
                @keyup.enter="addPromptItem(section.kind)"
                class="flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs focus:outline-none focus:border-amber-500"
              />
              <button
                @click="addPromptItem(section.kind)"
                :disabled="!newItemText[section.kind].trim()"
                class="text-xs bg-slate-700 hover:bg-slate-600 text-amber-500 px-3 py-1 rounded disabled:opacity-40"
              >
                + Ekle
              </button>
            </div>
          </div>

          <p class="text-xs text-slate-600 leading-relaxed border-t border-slate-700 pt-2">
            Sıra promptta birleşme sırasıdır: kalıcı kuralları üste, denemelik olanları alta koy.
          </p>

          <!-- Son N bölüm ayarı -->
          <div class="flex flex-col gap-1 border-t border-slate-700 pt-3">
            <label class="text-xs text-slate-500">Prompta tam metin girecek son bölüm sayısı</label>
            <div class="flex items-center gap-2">
              <input
                v-model.number="lastChaptersDraft"
                type="number"
                min="1"
                max="5"
                class="w-16 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs focus:outline-none focus:border-amber-500"
              />
              <button
                @click="saveLastChapters"
                class="bg-amber-600 hover:bg-amber-500 text-slate-900 text-xs font-bold px-4 py-1.5 rounded transition-colors"
              >
                {{ settingsSaved ? '✓ Kaydedildi' : 'Kaydet' }}
              </button>
            </div>
            <p class="text-xs text-slate-600 leading-relaxed">
              Daha fazlası tutarlılığı artırır ama yaratıcılığı düşürür ve token maliyetini
              yükseltir. Süreklilik zayıfsa çözüm genelde daha çok ham bölüm değil, daha iyi hafıza
              aramasıdır. (1-5, varsayılan 2)
            </p>
          </div>
        </div>
      </div>

      <!-- Yayımlama: hikayeyi okuyucu platformunda görünür kılar -->
      <div class="mb-4 border border-slate-700 rounded-lg flex flex-col min-h-0 shrink-0">
        <button
          @click="showPublishing = !showPublishing"
          class="w-full text-left px-4 py-2 text-sm font-semibold text-slate-300 hover:text-amber-500 transition-colors shrink-0"
        >
          🌍 Yayımlama
          <span class="text-xs font-normal text-slate-500">
            ({{
              store.story?.publishing?.visibility === 'public'
                ? 'herkese açık'
                : store.story?.publishing?.visibility === 'unlisted'
                  ? 'liste dışı'
                  : 'özel'
            }})
          </span>
          {{ showPublishing ? '▾' : '▸' }}
        </button>

        <div
          v-if="showPublishing"
          class="p-3 pt-0 flex flex-col gap-3 overflow-y-auto max-h-[55vh] min-h-0"
        >
          <div class="flex flex-col gap-1">
            <label class="text-xs text-slate-500">Görünürlük</label>
            <select
              v-model="pubVisibility"
              class="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs focus:outline-none focus:border-amber-500"
            >
              <option value="private">Özel — yalnızca sen</option>
              <option value="unlisted">Liste dışı — linki bilen okur</option>
              <option value="public">Herkese açık — ana sayfada ve aramada</option>
            </select>
          </div>

          <div class="flex flex-col gap-1">
            <label class="text-xs text-slate-500">Açıklama (okuyucu kartında görünür)</label>
            <textarea
              v-model="pubDescription"
              rows="3"
              maxlength="2000"
              class="bg-slate-900 border border-slate-700 rounded p-2 text-xs focus:outline-none focus:border-amber-500 resize-none"
            ></textarea>
          </div>

          <div class="flex flex-col gap-1">
            <label class="text-xs text-slate-500">Etiketler (virgülle ayır, en fazla 10)</label>
            <input
              v-model="pubTags"
              type="text"
              placeholder="fantasy, adventure"
              class="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs focus:outline-none focus:border-amber-500"
            />
          </div>

          <label class="flex items-start gap-2 text-xs text-slate-400">
            <input v-model="pubIsAdult" type="checkbox" class="mt-0.5" />
            <span
              >Yetişkin içerik.
              <b class="text-slate-500">Bu işaretliyken herkese açık yayımlanamaz.</b></span
            >
          </label>

          <label
            v-if="pubVisibility === 'public'"
            class="flex items-start gap-2 text-xs text-slate-400"
          >
            <input v-model="pubRulesAccepted" type="checkbox" class="mt-0.5" />
            <span>İçerik kurallarını okudum ve kabul ediyorum.</span>
          </label>

          <p v-if="pubError" class="text-xs text-red-400 leading-relaxed">{{ pubError }}</p>

          <button
            @click="savePublishing"
            class="bg-amber-600 hover:bg-amber-500 text-slate-900 text-xs font-bold px-4 py-1.5 rounded transition-colors"
          >
            {{ pubSaved ? '✓ Kaydedildi' : 'Kaydet' }}
          </button>

          <a
            v-if="store.story?.publishing?.visibility !== 'private'"
            :href="publicUrl"
            target="_blank"
            rel="noopener"
            class="text-xs text-amber-500 hover:underline break-all"
          >
            Okuyucu sayfasını aç: {{ publicUrl }}
          </a>

          <p class="text-xs text-slate-600 leading-relaxed">
            Yayımlanan hikayede yeni bölümler üretildikçe okurlara görünür — ayrı bir "yayımla"
            adımı yok.
          </p>
        </div>
      </div>

      <!-- Bölüm Özetleri -->
      <h2 class="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-3 shrink-0">
        Bölüm Özetleri
      </h2>
      <div class="flex-1 overflow-y-auto pr-2 flex flex-col gap-3">
        <p v-if="!store.story?.chapters?.length" class="text-sm text-slate-500">Henüz bölüm yok.</p>
        <div
          v-for="chapter in store.story?.chapters"
          :key="'sum-' + chapter.id"
          class="bg-slate-800/50 p-3 rounded-lg border border-slate-700/50"
        >
          <div class="flex justify-between items-center mb-1">
            <span class="text-xs font-bold text-amber-500">Bölüm {{ chapter.index }}</span>
            <button
              v-if="editingSummaryIndex !== chapter.index"
              @click="startSummaryEdit(chapter.index, chapter.summary)"
              class="text-xs text-slate-500 hover:text-amber-500"
            >
              düzenle
            </button>
          </div>
          <p
            v-if="editingSummaryIndex !== chapter.index"
            class="text-xs leading-relaxed text-slate-300"
          >
            {{ chapter.summary || '(özet yok)' }}
          </p>
          <div v-else class="flex flex-col gap-2">
            <textarea
              v-model="summaryDraft"
              rows="3"
              class="bg-slate-900 border border-slate-600 rounded p-2 text-xs focus:outline-none focus:border-amber-500 resize-none"
            ></textarea>
            <div class="flex gap-2 justify-end">
              <button
                @click="editingSummaryIndex = null"
                class="text-xs text-slate-400 hover:text-slate-200"
              >
                İptal
              </button>
              <button
                @click="saveSummaryEdit"
                class="text-xs bg-amber-600 hover:bg-amber-500 text-slate-900 font-bold px-3 py-1 rounded"
              >
                Kaydet
              </button>
            </div>
          </div>
        </div>
      </div>
    </aside>

    <!-- ORTA PANEL: Bölümler ve Input -->
    <main class="w-2/4 flex flex-col relative bg-slate-950">
      <div
        v-if="store.error"
        class="bg-red-900/50 border border-red-500 text-red-200 p-4 mx-10 mt-4 rounded-lg"
      >
        ⚠️ {{ store.error }}
      </div>

      <div ref="scrollContainer" class="flex-1 overflow-y-auto p-10 pb-36">
        <div v-for="chapter in chapters" :key="'ch-' + chapter.id" class="mb-10">
          <div class="flex justify-between items-center mb-3 border-b border-slate-800 pb-2">
            <span class="text-sm font-bold text-slate-500 uppercase tracking-wider"
              >Bölüm {{ chapter.index }}</span
            >
            <button
              v-if="editingChapterIndex !== chapter.index && !isBusy"
              @click="startChapterEdit(chapter.index, chapter.content)"
              class="text-xs bg-slate-800 hover:bg-slate-700 text-amber-500 px-3 py-1 rounded border border-slate-700 transition-colors"
            >
              Düzenle
            </button>
          </div>

          <div
            v-if="editingChapterIndex !== chapter.index"
            class="max-w-none text-gray-100 leading-relaxed whitespace-pre-wrap"
          >
            {{ chapter.content }}
          </div>

          <div v-else class="flex flex-col gap-3">
            <textarea
              v-model="chapterDraft"
              rows="14"
              class="w-full bg-slate-900 border border-slate-700 rounded-lg p-4 text-gray-100 focus:outline-none focus:border-amber-500 resize-y leading-relaxed"
            ></textarea>
            <div class="flex gap-2 justify-end">
              <button
                @click="editingChapterIndex = null"
                class="bg-slate-700 hover:bg-slate-600 px-4 py-2 rounded text-sm transition-colors"
              >
                İptal
              </button>
              <button
                @click="saveChapterEdit"
                class="bg-amber-600 hover:bg-amber-500 text-slate-900 font-bold px-6 py-2 rounded text-sm transition-colors"
                :disabled="store.isLoading"
              >
                {{ store.isLoading ? 'Kaydediliyor...' : 'Kaydet' }}
              </button>
            </div>
            <p class="text-xs text-slate-500 text-right">
              Kaydedince özet ve hafıza güncellenir; yapay zeka bir sonraki bölümde değişikliği
              bilir.
            </p>
          </div>
        </div>
      </div>

      <!-- Aksiyon Alanı -->
      <div
        class="absolute bottom-0 w-full p-6 bg-gradient-to-t from-slate-950 via-slate-950 to-transparent"
      >
        <form @submit.prevent="submitAction" class="flex gap-3 max-w-3xl mx-auto">
          <input
            v-model="userAction"
            type="text"
            placeholder="Bir sonraki hamleyi yaz (Örn: Kapıyı aç ve içeri gir)..."
            class="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-5 py-4 text-gray-100 focus:outline-none focus:border-amber-500 focus:ring-1 focus:ring-amber-500 transition-all shadow-lg"
            :disabled="store.isLoading"
          />
          <button
            type="submit"
            class="bg-amber-600 hover:bg-amber-500 text-slate-900 font-bold px-8 py-4 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-lg flex items-center gap-2"
            :disabled="store.isLoading || !userAction.trim()"
          >
            <span v-if="store.isLoading">Yazılıyor...</span>
            <span v-else>Devam Et</span>
          </button>
        </form>
      </div>
    </main>

    <!-- SAĞ PANEL: Lore ve Elementler -->
    <aside
      class="w-1/4 bg-slate-800 border-l border-slate-700 p-6 flex flex-col gap-6 overflow-y-auto"
    >
      <h2 class="text-lg font-bold text-slate-100 border-b border-slate-700 pb-2">Keşfedilenler</h2>

      <div v-for="section in elementSections" :key="section.kind">
        <div class="flex justify-between items-center mb-3">
          <h3 class="text-xs uppercase tracking-wider font-semibold" :class="section.color">
            {{ section.title }} ({{ section.items.length }})
          </h3>
          <button
            @click="addingElementKind = addingElementKind === section.kind ? null : section.kind"
            class="text-xs text-slate-500 hover:text-amber-500"
          >
            + Ekle
          </button>
        </div>

        <!-- Yeni öğe formu -->
        <div
          v-if="addingElementKind === section.kind"
          class="bg-slate-700/40 p-3 rounded border border-slate-600 mb-3 flex flex-col gap-2"
        >
          <input
            v-model="newElementName"
            type="text"
            placeholder="İsim"
            class="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs focus:outline-none focus:border-amber-500"
          />
          <textarea
            v-model="newElementDesc"
            rows="2"
            placeholder="Açıklama"
            class="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs focus:outline-none focus:border-amber-500 resize-none"
          ></textarea>
          <button
            @click="saveNewElement"
            class="self-end text-xs bg-amber-600 hover:bg-amber-500 text-slate-900 font-bold px-3 py-1 rounded"
          >
            Ekle
          </button>
        </div>

        <div class="flex flex-col gap-3">
          <div
            v-for="element in section.items"
            :key="section.kind + '-' + element.id"
            class="bg-slate-700/40 p-3 rounded border border-slate-600"
          >
            <template
              v-if="!(editingElement?.kind === section.kind && editingElement?.id === element.id)"
            >
              <div class="flex justify-between items-start">
                <div class="font-bold text-sm text-slate-200">{{ element.name }}</div>
                <div class="flex gap-2 text-xs">
                  <button
                    @click="startElementEdit(section.kind, element)"
                    class="text-slate-500 hover:text-amber-500"
                  >
                    ✎
                  </button>
                  <button
                    @click="removeElement(section.kind, element.id)"
                    class="text-slate-500 hover:text-red-500"
                  >
                    ✕
                  </button>
                </div>
              </div>
              <div class="text-xs text-slate-400 mt-1">{{ element.description }}</div>
              <div v-if="element.status" class="text-xs text-emerald-400/80 mt-1 italic">
                Durum: {{ element.status }}
              </div>
            </template>

            <div v-else class="flex flex-col gap-2">
              <input
                v-model="elementNameDraft"
                type="text"
                class="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs focus:outline-none focus:border-amber-500"
              />
              <textarea
                v-model="elementDescDraft"
                rows="3"
                class="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs focus:outline-none focus:border-amber-500 resize-none"
              ></textarea>
              <div class="flex gap-2 justify-end">
                <button
                  @click="editingElement = null"
                  class="text-xs text-slate-400 hover:text-slate-200"
                >
                  İptal
                </button>
                <button
                  @click="saveElementEdit"
                  class="text-xs bg-amber-600 hover:bg-amber-500 text-slate-900 font-bold px-3 py-1 rounded"
                >
                  Kaydet
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </aside>
  </div>
</template>
