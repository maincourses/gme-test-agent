<script setup>
import { Clipboard, FileCode2, FlaskConical, GitPullRequest, Hammer, Play, Repeat2, Trash2 } from "@lucide/vue";
import ArtifactTabs from "../components/ArtifactTabs.vue";
import JobTable from "../components/JobTable.vue";
import MetricStrip from "../components/MetricStrip.vue";
import { useWorkspace } from "../composables/useWorkspace";

const {
  busyAction,
  jobStats,
  selectedJob,
  selectedJobOpenFailures,
  testForm,
  moduleOptions,
  generatedTestInfo,
  workflowSteps,
  createTestJob,
  extendSelectedTestJob,
  buildSelectedJob,
  runSelectedTests,
  createSkipPrForSelectedJob,
  cleanupSelectedJob,
  deleteSelectedJob,
  copyText,
  jobStatus,
  statusTone,
} = useWorkspace();
</script>

<template>
  <section class="page test-workbench">
    <div class="page-heading">
      <div>
        <span class="eyebrow">TEST AGENT</span>
        <h1>测试 Agent 工作台</h1>
      </div>
      <MetricStrip
        :items="[
          { label: '运行中', value: jobStats.running },
          { label: '待审查', value: jobStats.review },
          { label: '失败', value: jobStats.failed },
        ]"
      />
    </div>

    <div class="workbench-grid">
      <section class="panel create-panel">
        <div class="panel-title-row">
          <h2>测试扩展</h2>
          <span class="mini-badge">GME vs ACIS</span>
        </div>

        <label class="field">
          <span>模块</span>
          <select v-model="testForm.module">
            <option v-for="item in moduleOptions" :key="item" :value="item">{{ item }}</option>
          </select>
        </label>

        <label class="field">
          <span>测试目标 / 提示词</span>
          <textarea
            v-model="testForm.apiName"
            rows="7"
            placeholder="例如：继续扩展 laws 模块中字符串解析、表达式求值相关的 GME vs ACIS 对比测试，补充边界输入和多变量表达式场景"
          ></textarea>
        </label>

        <div class="generated-target">
          <FileCode2 :size="17" />
          <div>
            <span>目标测试文件</span>
            <code>{{ generatedTestInfo.file }}</code>
          </div>
        </div>

        <div class="action-stack">
          <button class="primary-button" type="button" :disabled="!!busyAction" @click="createTestJob">
            <FlaskConical :size="16" />
            新建任务并生成
          </button>
          <button class="ghost-button" type="button" :disabled="!!busyAction || !selectedJob?.worktree_path" @click="extendSelectedTestJob">
            <Repeat2 :size="16" />
            继续扩展选中任务
          </button>
        </div>
      </section>

      <section class="panel current-job-panel">
        <div class="panel-title-row">
          <h2>当前任务</h2>
          <span v-if="selectedJob" class="status-pill" :class="statusTone(selectedJob.status)">{{ jobStatus(selectedJob) }}</span>
        </div>

        <div v-if="selectedJob" class="job-summary">
          <div>
            <span>ID</span>
            <code>{{ selectedJob.id.slice(0, 8) }}</code>
          </div>
          <div>
            <span>模块</span>
            <strong>{{ selectedJob.module || "-" }}</strong>
          </div>
          <div>
            <span>目标仓库</span>
            <strong>{{ selectedJob.metadata?.target_repo || "-" }}</strong>
          </div>
          <div>
            <span>建议 Filter</span>
            <div class="summary-action">
              <strong>{{ generatedTestInfo.filterSummary }}</strong>
              <button class="ghost-button compact" type="button" @click="copyText(generatedTestInfo.filter)">
                <Clipboard :size="14" />
                复制 Filter
              </button>
            </div>
          </div>
        </div>
        <p v-else class="empty-hint">还没有选中任务。可以先新建一个测试任务。</p>

        <div class="workflow">
          <div v-for="step in workflowSteps" :key="step.label" class="workflow-step" :class="step.state">
            <span class="step-dot"></span>
            <div>
              <strong>{{ step.label }}</strong>
              <small>{{ step.detail }}</small>
            </div>
          </div>
        </div>
      </section>

      <section class="panel run-panel">
        <div class="panel-title-row">
          <h2>构建与验证</h2>
          <button class="ghost-button compact" type="button" @click="copyText(selectedJob?.worktree_path || '')">
            <Clipboard :size="15" />
            复制工作区
          </button>
        </div>

        <label class="field">
          <span>GTest 过滤器</span>
          <input v-model="testForm.gtestFilter" :placeholder="generatedTestInfo.filter" />
        </label>

        <div class="action-row">
          <button class="ghost-button" type="button" :disabled="!!busyAction || !selectedJob" @click="buildSelectedJob">
            <Hammer :size="16" />
            构建
          </button>
          <button class="ghost-button" type="button" :disabled="!!busyAction || !selectedJob" @click="runSelectedTests">
            <Play :size="16" />
            运行测试
          </button>
          <button class="success-button" type="button" :disabled="!!busyAction || !selectedJob || !selectedJobOpenFailures.length" @click="createSkipPrForSelectedJob">
            <GitPullRequest :size="16" />
            加 skip 并创建 PR
          </button>
        </div>

        <div class="action-row danger-row">
          <button class="danger-button" type="button" :disabled="!!busyAction || !selectedJob" @click="cleanupSelectedJob">
            <Trash2 :size="16" />
            清理工作区
          </button>
          <button class="danger-button" type="button" :disabled="!!busyAction || !selectedJob" @click="deleteSelectedJob">
            <Trash2 :size="16" />
            删除记录
          </button>
        </div>
      </section>
    </div>

    <JobTable />
    <ArtifactTabs />
  </section>
</template>
