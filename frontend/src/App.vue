<script setup>
import { computed, onMounted, ref } from "vue"

const roles = ref([])
const questions = ref([])
const selectedRoleId = ref("")
const selectedCategory = ref("全部")
const loading = ref(true)
const errorMessage = ref("")

const categories = computed(() => [
  "全部",
  ...new Set(questions.value.map((question) => question.category)),
])

const visibleQuestions = computed(() => {
  if (selectedCategory.value === "全部") {
    return questions.value
  }
  return questions.value.filter(
    (question) => question.category === selectedCategory.value,
  )
})

async function loadQuestions(roleId) {
  selectedRoleId.value = roleId
  selectedCategory.value = "全部"
  loading.value = true
  errorMessage.value = ""

  try {
    const response = await fetch(
      "/api/questions?role_id=" + encodeURIComponent(roleId),
    )
    if (!response.ok) {
      throw new Error("题库暂时不可用")
    }
    questions.value = await response.json()
  } catch (error) {
    errorMessage.value = error.message || "无法连接后端服务"
    questions.value = []
  } finally {
    loading.value = false
  }
}

async function initialize() {
  try {
    const response = await fetch("/api/roles")
    if (!response.ok) {
      throw new Error("岗位信息加载失败")
    }
    roles.value = await response.json()
    if (roles.value.length > 0) {
      await loadQuestions(roles.value[0].id)
    } else {
      loading.value = false
    }
  } catch (error) {
    errorMessage.value = error.message || "无法连接后端服务"
    loading.value = false
  }
}

onMounted(initialize)
</script>

<template>
  <main>
    <section class="hero">
      <nav class="nav-shell">
        <a class="brand" href="#" aria-label="职镜首页">
          <span class="brand-mark">职</span>
          <span>职镜</span>
        </a>
        <span class="stage-badge">工程实训 · 阶段 2</span>
      </nav>

      <div class="hero-content">
        <div>
          <p class="eyebrow">AI INTERVIEW COACH</p>
          <h1>让每一次开口，<br /><span>都有清晰的进步。</span></h1>
          <p class="hero-copy">
            从回答结构到表达节奏，获得有证据、可执行的中文面试训练反馈。
          </p>
        </div>

        <aside class="status-card">
          <p class="status-label">首版训练流程</p>
          <ol>
            <li><span>01</span>选择岗位与问题</li>
            <li><span>02</span>录制中文回答</li>
            <li><span>03</span>查看分析与建议</li>
          </ol>
          <p class="status-note">当前已完成岗位与题库浏览</p>
        </aside>
      </div>
    </section>

    <section class="content-shell">
      <div class="section-heading">
        <div>
          <p class="eyebrow dark">QUESTION BANK</p>
          <h2>从一个具体问题开始</h2>
        </div>
        <p>题库目前为 AI 初稿，需经团队人工审核后用于正式评测。</p>
      </div>

      <div v-if="roles.length" class="role-tabs" aria-label="岗位选择">
        <button
          v-for="role in roles"
          :key="role.id"
          :class="{ active: selectedRoleId === role.id }"
          type="button"
          @click="loadQuestions(role.id)"
        >
          {{ role.name }}
          <span>{{ role.question_count }} 题</span>
        </button>
      </div>

      <div v-if="categories.length > 1" class="filters">
        <button
          v-for="category in categories"
          :key="category"
          :class="{ active: selectedCategory === category }"
          type="button"
          @click="selectedCategory = category"
        >
          {{ category }}
        </button>
      </div>

      <div v-if="loading" class="state-panel">正在加载题库…</div>
      <div v-else-if="errorMessage" class="state-panel error">
        <strong>加载失败</strong>
        <span>{{ errorMessage }}，请确认后端服务已启动。</span>
      </div>
      <div v-else class="question-grid">
        <article
          v-for="(question, index) in visibleQuestions"
          :key="question.id"
          class="question-card"
        >
          <div class="card-meta">
            <span>{{ question.category }}</span>
            <span>建议 {{ question.duration_sec[0] }}–{{ question.duration_sec[1] }} 秒</span>
          </div>
          <p class="question-number">
            {{ String(index + 1).padStart(2, "0") }}
          </p>
          <h3>{{ question.question }}</h3>
          <div class="point-list">
            <span
              v-for="point in question.expected_points.slice(0, 4)"
              :key="point"
            >
              {{ point }}
            </span>
          </div>
          <button class="start-button" type="button" disabled>
            录音功能将在下一阶段接入
          </button>
        </article>
      </div>
    </section>
  </main>
</template>

