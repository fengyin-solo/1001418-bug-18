<template>
  <section class="page" data-module="work">
    <header class="page-head">
      <div>
        <h2>养护施工管理</h2>
        <p class="page-desc">维护施工任务，围绕施工编号、关联计划、承接单位、开工日期做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记施工任务</button>
        <button class="btn" type="button" @click="exportRows">导出养护施工清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ displayValue(row, column) }}</td>
          <td class="row-actions">
            <button
              v-for="action in allowedActions(String(row.status))"
              :key="action"
              class="link"
              type="button"
              :disabled="busyKey === actionKey(String(row.id), action)"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button class="link" type="button" @click="openDetail(row)">查看详情</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无养护施工数据，可先登记施工任务</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条养护施工记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-else-if="successMessage" class="success-text">{{ successMessage }}</span>
    </footer>

    <!-- 任务详情：字段与列表同源，动作执行后重新拉取，不存在不同步 -->
    <div v-if="detail" class="modal-mask" @click.self="closeDetail">
      <div class="modal-card">
        <header class="modal-head">
          <h3>施工任务详情 · {{ detail['施工编号'] }}</h3>
          <button class="link" type="button" @click="closeDetail">关闭</button>
        </header>
        <dl class="detail-grid">
          <div v-for="field in detailFields" :key="field" class="detail-item">
            <dt>{{ field }}</dt>
            <dd>{{ displayValue(detail, field) }}</dd>
          </div>
        </dl>
        <div class="modal-actions">
          <button
            v-for="action in allowedActions(String(detail.status))"
            :key="action"
            class="btn"
            :class="{ primary: action === '确认完工' }"
            type="button"
            :disabled="busyKey === actionKey(String(detail.id), action)"
            @click="runAction(action, detail)"
          >
            {{ action }}
          </button>
        </div>
      </div>
    </div>

    <!-- 确认完工前必须补齐完工资料 -->
    <div v-if="completion.target" class="modal-mask" @click.self="closeCompletion">
      <form class="modal-card" @submit.prevent="submitCompletion">
        <header class="modal-head">
          <h3>确认完工 · {{ completion.target['施工编号'] }}</h3>
          <button class="link" type="button" @click="closeCompletion">取消</button>
        </header>
        <p class="page-desc">字段没填全不允许确认完工，请补齐以下完工资料：</p>
        <label v-for="field in completionFields" :key="field" class="filter-item">
          <span>{{ field }}</span>
          <input v-model="completion.form[field]" :placeholder="`请输入${field}`" />
        </label>
        <p v-if="completion.error" class="error-text">{{ completion.error }}</p>
        <div class="modal-actions">
          <button class="btn primary" type="submit" :disabled="completion.sending">
            {{ completion.sending ? '提交中…' : '确认完工' }}
          </button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/work'
const columns = ["施工编号", "关联计划", "承接单位", "开工日期", "完工日期", "完成工程量", "监理人员", "施工状态"]
const detailFields = ["施工编号", "关联计划", "承接单位", "开工日期", "完工日期", "完成工程量", "监理人员", "施工状态"]
const completionFields = ["完工日期", "完成工程量", "监理人员"]
// 状态 → 当前允许的动作，与后端状态机保持一致
const ACTIONS_BY_STATUS: Record<string, string[]> = {
  '待开工': ['确认开工'],
  '施工中': ['提交验收'],
  '待验收': ['确认完工'],
  '已完工': [],
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const successMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
// 卡片件数由 /stats 按全量数据计算，跟筛选后的列表互不干扰
const stats = ref([
  { label: '待开工施工', value: 0 },
  { label: '施工中单据', value: 0 },
  { label: '本月完工数', value: 0 },
])

// 同一任务同一动作进行中时禁用按钮，从 UI 这一头挡住重复点击
const busyKey = ref('')
function actionKey(id: string, action: string) {
  return `${id}:${action}`
}
function allowedActions(status: string): string[] {
  return ACTIONS_BY_STATUS[status] ?? []
}
// 施工状态列以后端真实状态为准，避免旧的"施工状态"文本字段与流转脱节
function displayValue(row: Row, column: string): string | number {
  if (column === '施工状态') return String(row.status ?? '')
  const value = row[column]
  return value === null || value === undefined || value === '' ? '—' : value
}

const detail = ref<Row | null>(null)

const completion = reactive<{
  target: Row | null
  form: Record<string, string>
  error: string
  sending: boolean
}>({
  target: null,
  form: { 完工日期: '', 完成工程量: '', 监理人员: '' },
  error: '',
  sending: false,
})

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '施工任务登记入口尚未接入审批流'
}

async function openDetail(row: Row) {
  // 详情以服务端单条记录为准，不依赖列表里的快照，避免承接单位等字段不同步
  detail.value = { ...row }
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (response.ok) {
      detail.value = await response.json()
    }
  } catch {
    // 拉取失败时保留列表快照，弹层仍可查看
  }
}

function closeDetail() {
  detail.value = null
}

function openCompletion(row: Row) {
  completion.target = { ...row }
  completion.form = {
    完工日期: String(row['完工日期'] || ''),
    完成工程量: String(row['完成工程量'] || ''),
    监理人员: String(row['监理人员'] || ''),
  }
  completion.error = ''
}

function closeCompletion() {
  if (completion.sending) return
  completion.target = null
  completion.error = ''
}

async function extractError(response: Response, fallback: string): Promise<string> {
  try {
    const payload = await response.json()
    if (payload?.detail) return String(payload.detail)
    if (payload?.message) return String(payload.message)
  } catch {
    // 响应不是 JSON 时用兜底文案
  }
  return fallback
}

async function runAction(action: string, row: Row) {
  if (busyKey.value) return
  if (action === '确认完工') {
    openCompletion(row)
    return
  }
  await dispatchAction(action, String(row.id), {})
}

async function submitCompletion() {
  if (!completion.target || completion.sending) return
  completion.error = ''
  completion.sending = true
  const id = String(completion.target.id)
  try {
    await dispatchAction('确认完工', id, { ...completion.form }, () => {
      completion.sending = false
    })
    if (!completion.error) {
      completion.target = null
    }
  } finally {
    completion.sending = false
  }
}

async function dispatchAction(
  action: string,
  id: string,
  extra: Record<string, string>,
  onFinish?: () => void,
) {
  errorMessage.value = ''
  successMessage.value = ''
  busyKey.value = actionKey(id, action)
  try {
    const response = await request(`${ENDPOINT}/${id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, ...extra } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      const reason = payload?.detail || payload?.message || '养护施工动作未生效'
      if (completion.target && action === '确认完工') {
        completion.error = reason
      } else {
        errorMessage.value = reason
      }
      return
    }
    successMessage.value = payload.message || '操作已生效'
    detail.value = null
    await reload()
  } catch (error) {
    const reason = error instanceof Error ? error.message : '养护施工操作失败'
    if (completion.target && action === '确认完工') {
      completion.error = reason
    } else {
      errorMessage.value = reason
    }
  } finally {
    busyKey.value = ''
    onFinish?.()
  }
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) return
    const payload = await response.json()
    const counts = payload.counts ?? {}
    stats.value[0].value = counts['待开工'] ?? 0
    stats.value[1].value = counts['施工中'] ?? 0
    stats.value[2].value = payload['本月完工数'] ?? 0
  } catch {
    // 卡片拉取失败不影响列表使用
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error(await extractError(response, '施工任务列表读取失败'))
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    await reloadStats()
    // 详情弹层开着时同步刷新同一条任务，保证字段不落后
    if (detail.value) {
      const latest = rows.value.find((item) => String(item.id) === String(detail.value?.id))
      if (latest) detail.value = { ...latest }
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '养护施工列表读取失败'
  }
}

onMounted(reload)
</script>
