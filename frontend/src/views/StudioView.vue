<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useStoryStore } from '@/stores/storyStore'
import { useLlmKeyStore } from '@/stores/llmKeyStore'
import type { ElementDto, ElementKind } from '@/types'

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

// --- Yazım ayarları (style / negative prompt) ---
const showSettings = ref(false)
const styleDraft = ref('')
const negativeDraft = ref('')
const settingsSaved = ref(false)

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
    styleDraft.value = store.story?.stylePrompt || ''
    negativeDraft.value = store.story?.negativePrompt || ''
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

// --- Ayarlar ---
const saveSettings = async () => {
  await store.updateSettings(storyId.value, styleDraft.value, negativeDraft.value)
  settingsSaved.value = true
  setTimeout(() => (settingsSaved.value = false), 2000)
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
  { kind: 'characters' as ElementKind, title: 'Karakterler', color: 'text-amber-500', items: store.story?.characters || [] },
  { kind: 'locations' as ElementKind, title: 'Mekanlar', color: 'text-emerald-500', items: store.story?.locations || [] },
  { kind: 'items' as ElementKind, title: 'Eşyalar', color: 'text-cyan-500', items: store.story?.items || [] },
])
</script>

<template>
  <div class="h-screen w-full bg-slate-900 text-gray-200 flex overflow-hidden font-sans">
    <!-- SOL PANEL: Ayarlar ve Bölüm Özetleri -->
    <aside class="w-1/4 bg-slate-800 border-r border-slate-700 p-6 flex flex-col">
      <h1 class="text-2xl font-bold text-amber-500 mb-2">
        {{ store.story?.title || 'Yükleniyor...' }}
      </h1>
      <div class="flex items-center gap-2 mb-4 text-sm text-slate-400">
        <span class="bg-slate-700 px-2 py-1 rounded">Durum: {{ store.story?.status || '...' }}</span>
        <span class="bg-slate-700 px-2 py-1 rounded">Bölüm: {{ store.story?.actionCount || 0 }}</span>
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
      <div class="mb-4 border border-slate-700 rounded-lg">
        <button
          @click="showSettings = !showSettings"
          class="w-full text-left px-4 py-2 text-sm font-semibold text-slate-300 hover:text-amber-500 transition-colors"
        >
          ⚙️ Yazım Ayarları {{ showSettings ? '▾' : '▸' }}
        </button>
        <div v-if="showSettings" class="p-3 pt-0 flex flex-col gap-2">
          <label class="text-xs text-slate-500">Talimat (her bölümde uygulanır)</label>
          <textarea
            v-model="styleDraft"
            rows="3"
            placeholder="Örn: Karanlık ve şiirsel bir ton kullan, diyaloglara ağırlık ver..."
            class="bg-slate-900 border border-slate-700 rounded p-2 text-xs focus:outline-none focus:border-amber-500 resize-none"
          ></textarea>
          <label class="text-xs text-slate-500">Negatif talimat (bunlardan kaçınılır)</label>
          <textarea
            v-model="negativeDraft"
            rows="3"
            placeholder="Örn: Modern teknolojiden bahsetme, karakterleri öldürme..."
            class="bg-slate-900 border border-slate-700 rounded p-2 text-xs focus:outline-none focus:border-amber-500 resize-none"
          ></textarea>
          <button
            @click="saveSettings"
            class="self-end bg-amber-600 hover:bg-amber-500 text-slate-900 text-xs font-bold px-4 py-1.5 rounded transition-colors"
          >
            {{ settingsSaved ? '✓ Kaydedildi' : 'Kaydet' }}
          </button>
        </div>
      </div>

      <!-- Bölüm Özetleri -->
      <h2 class="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-3">
        Bölüm Özetleri
      </h2>
      <div class="flex-1 overflow-y-auto pr-2 flex flex-col gap-3">
        <p v-if="!store.story?.chapters?.length" class="text-sm text-slate-500">
          Henüz bölüm yok.
        </p>
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
          <p v-if="editingSummaryIndex !== chapter.index" class="text-xs leading-relaxed text-slate-300">
            {{ chapter.summary || '(özet yok)' }}
          </p>
          <div v-else class="flex flex-col gap-2">
            <textarea
              v-model="summaryDraft"
              rows="3"
              class="bg-slate-900 border border-slate-600 rounded p-2 text-xs focus:outline-none focus:border-amber-500 resize-none"
            ></textarea>
            <div class="flex gap-2 justify-end">
              <button @click="editingSummaryIndex = null" class="text-xs text-slate-400 hover:text-slate-200">İptal</button>
              <button @click="saveSummaryEdit" class="text-xs bg-amber-600 hover:bg-amber-500 text-slate-900 font-bold px-3 py-1 rounded">Kaydet</button>
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
        <div
          v-for="chapter in chapters"
          :key="'ch-' + chapter.id"
          class="mb-10"
        >
          <div class="flex justify-between items-center mb-3 border-b border-slate-800 pb-2">
            <span class="text-sm font-bold text-slate-500 uppercase tracking-wider">Bölüm {{ chapter.index }}</span>
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
          >{{ chapter.content }}</div>

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
              Kaydedince özet ve hafıza güncellenir; yapay zeka bir sonraki bölümde değişikliği bilir.
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
            <template v-if="!(editingElement?.kind === section.kind && editingElement?.id === element.id)">
              <div class="flex justify-between items-start">
                <div class="font-bold text-sm text-slate-200">{{ element.name }}</div>
                <div class="flex gap-2 text-xs">
                  <button @click="startElementEdit(section.kind, element)" class="text-slate-500 hover:text-amber-500">✎</button>
                  <button @click="removeElement(section.kind, element.id)" class="text-slate-500 hover:text-red-500">✕</button>
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
                <button @click="editingElement = null" class="text-xs text-slate-400 hover:text-slate-200">İptal</button>
                <button @click="saveElementEdit" class="text-xs bg-amber-600 hover:bg-amber-500 text-slate-900 font-bold px-3 py-1 rounded">Kaydet</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </aside>
  </div>
</template>
