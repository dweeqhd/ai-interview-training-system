<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue"

const roles = ref([])
const questions = ref([])
const selectedRoleId = ref("")
const selectedCategory = ref("全部")
const loading = ref(true)
const errorMessage = ref("")
const selectedQuestion = ref(null)
const recordingState = ref("idle")
const recorderMessage = ref("")
const mediaRecorder = ref(null)
const mediaStream = ref(null)
const recordedBlob = ref(null)
const recordedFileName = ref("")
const audioUrl = ref("")
const recordingSeconds = ref(0)
const currentSessionId = ref("")
const currentAnswer = ref(null)
let recordingTimer = null
let pollTimer = null
let recordingStartedAt = 0

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

function clearTimers() {
  if (recordingTimer) {
    window.clearInterval(recordingTimer)
    recordingTimer = null
  }
  if (pollTimer) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

function releaseMicrophone() {
  mediaStream.value?.getTracks().forEach((track) => track.stop())
  mediaStream.value = null
}

function abortRecording() {
  const recorder = mediaRecorder.value
  if (recorder?.state === "recording") {
    recorder.ondataavailable = null
    recorder.onstop = null
    recorder.stop()
  }
  mediaRecorder.value = null
  releaseMicrophone()
}

function clearRecording() {
  if (audioUrl.value) {
    URL.revokeObjectURL(audioUrl.value)
  }
  audioUrl.value = ""
  recordedBlob.value = null
  recordedFileName.value = ""
  recordingSeconds.value = 0
  currentAnswer.value = null
  recorderMessage.value = ""
  recordingState.value = "idle"
}

async function openPractice(question) {
  clearTimers()
  abortRecording()
  clearRecording()
  selectedQuestion.value = question
  await nextTick()
  document.querySelector(".recorder-shell")?.scrollIntoView({
    behavior: "smooth",
    block: "center",
  })
}

function closePractice() {
  clearTimers()
  abortRecording()
  clearRecording()
  selectedQuestion.value = null
}

function supportedMimeType() {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
  ]
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || ""
}

async function startRecording() {
  recorderMessage.value = ""
  currentAnswer.value = null
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    recorderMessage.value = "当前浏览器不支持网页录音，请改用音频文件上传。"
    return
  }

  try {
    clearRecording()
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    mediaStream.value = stream
    const mimeType = supportedMimeType()
    const recorder = mimeType
      ? new MediaRecorder(stream, { mimeType })
      : new MediaRecorder(stream)
    const chunks = []
    mediaRecorder.value = recorder
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data)
    }
    recorder.onstop = () => {
      const blob = new Blob(chunks, {
        type: recorder.mimeType || "audio/webm",
      })
      recordedBlob.value = blob
      recordedFileName.value = blob.type.includes("mp4")
        ? "interview-answer.m4a"
        : "interview-answer.webm"
      audioUrl.value = URL.createObjectURL(blob)
      recordingState.value = "ready"
      releaseMicrophone()
    }
    recorder.start(500)
    recordingStartedAt = Date.now()
    recordingState.value = "recording"
    recordingTimer = window.setInterval(() => {
      recordingSeconds.value = Math.floor(
        (Date.now() - recordingStartedAt) / 1000,
      )
    }, 250)
  } catch (error) {
    releaseMicrophone()
    recorderMessage.value =
      error.name === "NotAllowedError"
        ? "麦克风权限未开启；你也可以直接上传已有音频。"
        : "无法启动录音，请检查麦克风是否被其他程序占用。"
  }
}

function stopRecording() {
  if (mediaRecorder.value?.state === "recording") {
    mediaRecorder.value.stop()
  }
  if (recordingTimer) {
    window.clearInterval(recordingTimer)
    recordingTimer = null
  }
}

function selectAudioFile(event) {
  const file = event.target.files?.[0]
  if (!file) return
  clearRecording()
  recordedBlob.value = file
  recordedFileName.value = file.name
  audioUrl.value = URL.createObjectURL(file)
  recordingState.value = "ready"
}

async function ensureSession() {
  if (currentSessionId.value) return currentSessionId.value
  const response = await fetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role_id: selectedRoleId.value }),
  })
  if (!response.ok) throw new Error("无法创建训练会话")
  const session = await response.json()
  currentSessionId.value = session.id
  return session.id
}

async function submitAnswer() {
  if (!recordedBlob.value || !selectedQuestion.value) return
  recordingState.value = "uploading"
  recorderMessage.value = "正在上传并检查音频…"
  try {
    const sessionId = await ensureSession()
    const formData = new FormData()
    formData.append("question_id", selectedQuestion.value.id)
    formData.append("audio", recordedBlob.value, recordedFileName.value)
    const response = await fetch(`/api/sessions/${sessionId}/answers`, {
      method: "POST",
      body: formData,
    })
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload.detail || "音频提交失败")
    }
    currentAnswer.value = payload
    recordingState.value = payload.task.status
    recorderMessage.value = "音频已接收，正在进行本地语音分析…"
    pollAnswer(payload.id)
  } catch (error) {
    recordingState.value = "ready"
    recorderMessage.value = error.message || "提交失败，请稍后重试"
  }
}

async function pollAnswer(answerId) {
  try {
    const response = await fetch(`/api/answers/${answerId}`)
    if (!response.ok) throw new Error("读取分析状态失败")
    const answer = await response.json()
    currentAnswer.value = answer
    recordingState.value = answer.task.status
    if (answer.task.status === "completed") {
      recorderMessage.value = "分析完成。以下指标仅用于训练反馈。"
      return
    }
    if (answer.task.status === "failed") {
      recorderMessage.value = answer.task.error_message || "分析失败，请重新提交"
      return
    }
    pollTimer = window.setTimeout(() => pollAnswer(answerId), 2000)
  } catch (error) {
    recordingState.value = "failed"
    recorderMessage.value = error.message || "读取分析状态失败"
  }
}

function formatTime(seconds) {
  const minutes = Math.floor(seconds / 60)
  const remaining = String(seconds % 60).padStart(2, "0")
  return `${minutes}:${remaining}`
}

onBeforeUnmount(() => {
  clearTimers()
  abortRecording()
  if (audioUrl.value) URL.revokeObjectURL(audioUrl.value)
})
</script>

<template>
  <main>
    <section class="hero">
      <nav class="nav-shell">
        <a class="brand" href="#" aria-label="职镜首页">
          <span class="brand-mark">职</span>
          <span>职镜</span>
        </a>
        <span class="stage-badge">工程实训 · 阶段 3</span>
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
          <p class="status-note">当前可录音、上传并运行本地语音分析</p>
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
          <button class="start-button" type="button" @click="openPractice(question)">
            开始练习
          </button>
        </article>
      </div>

      <section v-if="selectedQuestion" class="recorder-shell" aria-live="polite">
        <button class="close-button" type="button" aria-label="关闭练习" @click="closePractice">
          ×
        </button>
        <div class="recorder-heading">
          <div>
            <p class="eyebrow dark">PRACTICE ROOM</p>
            <h2>{{ selectedQuestion.question }}</h2>
          </div>
          <span>{{ selectedQuestion.category }}</span>
        </div>

        <div class="privacy-note">
          录音仅保存在本机项目目录并用于训练分析，不会自动上传到云端。
        </div>

        <div class="recorder-controls">
          <div class="record-status" :class="recordingState">
            <span class="record-dot"></span>
            <strong v-if="recordingState === 'recording'">
              录音中 {{ formatTime(recordingSeconds) }}
            </strong>
            <strong v-else-if="recordingState === 'ready'">音频已准备</strong>
            <strong v-else-if="['uploading', 'queued', 'processing'].includes(recordingState)">
              本地分析中
            </strong>
            <strong v-else-if="recordingState === 'completed'">分析完成</strong>
            <strong v-else-if="recordingState === 'failed'">分析失败</strong>
            <strong v-else>尚未录音</strong>
          </div>

          <div class="action-row">
            <button
              v-if="recordingState !== 'recording'"
              class="primary-action"
              type="button"
              :disabled="['uploading', 'queued', 'processing'].includes(recordingState)"
              @click="startRecording"
            >
              {{ recordedBlob ? "重新录音" : "开始录音" }}
            </button>
            <button v-else class="stop-action" type="button" @click="stopRecording">
              停止录音
            </button>

            <label class="upload-label">
              上传音频
              <input
                type="file"
                accept="audio/wav,audio/webm,audio/mpeg,audio/mp4,audio/ogg,audio/flac"
                :disabled="['recording', 'uploading', 'queued', 'processing'].includes(recordingState)"
                @change="selectAudioFile"
              />
            </label>
          </div>
        </div>

        <audio v-if="audioUrl" class="audio-player" :src="audioUrl" controls></audio>

        <div v-if="recordedBlob" class="submit-row">
          <span>{{ recordedFileName }}</span>
          <button
            type="button"
            :disabled="['uploading', 'queued', 'processing'].includes(recordingState)"
            @click="submitAnswer"
          >
            提交并分析
          </button>
        </div>

        <p v-if="recorderMessage" class="recorder-message">{{ recorderMessage }}</p>

        <div v-if="currentAnswer?.task.status === 'completed'" class="analysis-result">
          <div class="transcript-panel">
            <p>转写文本</p>
            <blockquote>{{ currentAnswer.transcript || "未识别到有效语音" }}</blockquote>
          </div>
          <div class="metric-grid">
            <article>
              <span>有效语速</span>
              <strong>{{ currentAnswer.metrics.speaking_rate_per_min }}</strong>
              <small>字/词组 · 分钟</small>
            </article>
            <article>
              <span>明显停顿</span>
              <strong>{{ currentAnswer.metrics.pause_count }}</strong>
              <small>≥ 0.5 秒</small>
            </article>
            <article>
              <span>最长停顿</span>
              <strong>{{ currentAnswer.metrics.longest_pause_sec }}</strong>
              <small>秒</small>
            </article>
            <article>
              <span>语气词</span>
              <strong>{{ currentAnswer.metrics.filler_count }}</strong>
              <small>仅作客观计数</small>
            </article>
          </div>
          <p class="metric-note">{{ currentAnswer.metrics.metric_note }}</p>
        </div>
      </section>
    </section>
  </main>
</template>
