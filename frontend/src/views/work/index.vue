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
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actionsFor(row)"
              :key="action"
              class="link"
              type="button"
              :disabled="acting"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!actionsFor(row).length" class="muted-text">已完工，无可用动作</span>
            <button class="link" type="button" @click="openDetail(row)">详情</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无养护施工数据，可先登记施工任务</td>
        </tr>
      </tbody>
    </table>

    <section v-if="detail" class="detail-card">
      <header class="detail-head">
        <h3>施工任务详情 · {{ detail['施工编号'] ?? detail.id }}</h3>
        <button class="link" type="button" @click="detail = null">收起</button>
      </header>
      <dl class="detail-grid">
        <template v-for="column in columns" :key="column">
          <dt>{{ column }}</dt>
          <dd>{{ detail[column] ?? '—' }}</dd>
        </template>
      </dl>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条养护施工记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/work'
const columns = ["施工编号", "关联计划", "承接单位", "开工日期", "完工日期", "完成工程量", "监理人员", "施工状态"]
// 与后端状态机保持一致：每个状态只放出允许执行的动作
const ACTION_FLOW: Record<string, string[]> = {
  '待开工': ['确认开工'],
  '施工中': ['提交验收'],
  '待验收': ['确认完工'],
  '已完工': [],
}
const stats = ref([{ label: '待开工施工', value: 0 }, { label: '施工中单据', value: 0 }, { label: '本月完工数', value: 0 }])

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const acting = ref(false)
const detail = ref<Row | null>(null)
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function actionsFor(row: Row): string[] {
  return ACTION_FLOW[String(row.status ?? row['施工状态'] ?? '')] ?? []
}

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

async function runAction(action: string, row: Row) {
  if (acting.value) {
    return
  }
  acting.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = (await response.json()) as { ok?: boolean; message?: string }
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '养护施工动作未生效，请稍后重试')
    }
    noticeMessage.value = payload.message || `施工任务已${action}`
    await Promise.all([reload(), loadStats(), refreshDetail(row.id)])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '养护施工操作失败'
  } finally {
    acting.value = false
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('施工任务详情读取失败')
    }
    detail.value = (await response.json()) as Row
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '施工任务详情读取失败'
  }
}

async function refreshDetail(entryId: string | number | null) {
  if (detail.value && String(detail.value.id) === String(entryId)) {
    const response = await request(`${ENDPOINT}/${entryId}`)
    if (response.ok) {
      detail.value = (await response.json()) as Row
    }
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}?size=200`)
    if (!response.ok) {
      return
    }
    const payload = await response.json()
    const all: Row[] = payload.items ?? []
    const month = new Date().toISOString().slice(0, 7)
    stats.value = [
      { label: '待开工施工', value: all.filter((row) => row.status === '待开工').length },
      { label: '施工中单据', value: all.filter((row) => row.status === '施工中').length },
      {
        label: '本月完工数',
        value: all.filter((row) => row.status === '已完工' && String(row['完工日期'] ?? '').startsWith(month)).length,
      },
    ]
  } catch {
    // 统计失败不阻断列表，保持上一次的数值
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('施工任务列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '养护施工列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadStats()
})
</script>
