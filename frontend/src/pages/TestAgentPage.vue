<script setup>
import { Clipboard, FileCode2, FlaskConical, Hammer, ListChecks, Play, Repeat2, Search, Trash2, X } from "@lucide/vue";
import ArtifactTabs from "../components/ArtifactTabs.vue";
import JobTable from "../components/JobTable.vue";
import MetricStrip from "../components/MetricStrip.vue";
import { useWorkspace } from "../composables/useWorkspace";

const {
  busyAction,
  jobStats,
  testWorkspaceTab,
  gtestFilterMode,
  selectedJob,
  testForm,
  moduleOptions,
  interfaceCatalog,
  interfaceCatalogLoading,
  interfaceSearch,
  activeCatalogFile,
  selectedInterfaceIds,
  catalogFiles,
  visibleCatalogInterfaces,
  selectedCatalogInterfaces,
  catalogSelectionSummary,
  generatedTestInfo,
  workflowSteps,
  createTestJob,
  extendSelectedTestJob,
  buildSelectedJob,
  runSelectedTests,
  cleanupSelectedJob,
  deleteSelectedJob,
  copyText,
  jobStatus,
  statusTone,
  selectCatalogFile,
  toggleCatalogInterface,
  clearCatalogSelection,
  clampTestsPerInterface,
} = useWorkspace();

function selectedInterfaceFile(item) {
  const path = String(item?.target_file || "").replace(/\\/g, "/");
  return path.split("/").pop() || path || "未知文件";
}
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

    <nav class="workspace-tabs" role="tablist" aria-label="测试 Agent 工作视图">
      <button
        type="button"
        role="tab"
        :aria-selected="testWorkspaceTab === 'generate'"
        :class="{ active: testWorkspaceTab === 'generate' }"
        @click="testWorkspaceTab = 'generate'"
      >
        <FlaskConical :size="17" />
        <span>生成测试</span>
        <small v-if="selectedInterfaceIds.length">{{ selectedInterfaceIds.length }}</small>
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="testWorkspaceTab === 'review'"
        :class="{ active: testWorkspaceTab === 'review' }"
        @click="testWorkspaceTab = 'review'"
      >
        <ListChecks :size="17" />
        <span>任务与结果</span>
        <small v-if="jobStats.review">{{ jobStats.review }}</small>
      </button>
    </nav>

    <div v-if="testWorkspaceTab === 'generate'" class="generation-layout">
      <section class="panel catalog-panel">
        <div class="panel-title-row">
          <div>
            <h2>接口选择</h2>
            <p class="panel-subtitle">按现有测试文件筛选，并选择本次要扩展的 GME vs ACIS 接口</p>
          </div>
          <span class="mini-badge">{{ interfaceCatalog.summary?.interface_count || 0 }} 个接口</span>
        </div>

        <div class="catalog-toolbar generation-catalog-toolbar">
          <label class="field compact-field">
            <span>模块</span>
            <select v-model="testForm.module">
              <option v-for="item in moduleOptions" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>
          <label class="field catalog-search">
            <span>搜索接口</span>
            <div class="search-input">
              <Search :size="15" />
              <input v-model="interfaceSearch" placeholder="函数名、UniqueSymbol、fixture" />
            </div>
          </label>
        </div>

        <div class="catalog-browser">
          <div class="catalog-file-pane">
            <div class="catalog-pane-heading">
              <strong>测试文件</strong>
              <span>{{ catalogFiles.length }} 个</span>
            </div>
            <div class="catalog-file-list">
              <button
                v-for="file in catalogFiles"
                :key="file.path"
                type="button"
                class="catalog-file-option"
                :class="{ selected: activeCatalogFile === file.path }"
                @click="selectCatalogFile(file.path)"
              >
                <FileCode2 :size="16" />
                <span>
                  <strong>{{ file.name }}</strong>
                  <small>{{ file.interface_count }} 个接口</small>
                </span>
              </button>
            </div>
          </div>

          <div class="catalog-interface-pane">
            <div class="catalog-pane-heading">
              <strong>可选接口</strong>
              <span>{{ visibleCatalogInterfaces.length }} 条结果</span>
            </div>
            <div v-if="interfaceCatalogLoading" class="catalog-empty">正在读取接口目录...</div>
            <div v-else-if="!activeCatalogFile" class="catalog-empty">请选择一个测试文件</div>
            <div v-else-if="!visibleCatalogInterfaces.length" class="catalog-empty">当前文件中没有匹配的接口</div>
            <div v-else class="catalog-interface-list">
              <label
                v-for="item in visibleCatalogInterfaces"
                :key="item.id"
                class="catalog-interface-option"
                :class="{ selected: selectedInterfaceIds.includes(item.id) }"
              >
                <input
                  type="checkbox"
                  :checked="selectedInterfaceIds.includes(item.id)"
                  @change="toggleCatalogInterface(item.id, $event.target.checked)"
                />
                <span class="catalog-interface-main">
                  <strong>{{ item.name }}</strong>
                  <code :title="item.unique_symbol">{{ item.unique_symbol }}</code>
                </span>
                <span class="catalog-interface-meta">
                  <small>{{ item.source_catalog.replace('_acis_symbol.csv', '') }}</small>
                  <small>{{ item.test_suite }}</small>
                  <small>已有 {{ item.existing_test_count }}</small>
                </span>
              </label>
            </div>
          </div>
        </div>
      </section>

      <aside class="generation-sidebar">
        <section class="panel create-panel generation-config-panel">
          <div class="panel-title-row">
            <h2>生成设置</h2>
            <span class="mini-badge">GME vs ACIS</span>
          </div>

          <div class="selected-interface-section">
            <div class="selected-interface-heading">
              <div>
                <strong>已选接口</strong>
                <span>{{ catalogSelectionSummary.interfaceCount }}/{{ catalogSelectionSummary.maxInterfaces }}</span>
              </div>
              <button class="ghost-button compact" type="button" :disabled="!selectedInterfaceIds.length" @click="clearCatalogSelection">
                <X :size="14" />
                清空
              </button>
            </div>
            <div v-if="selectedCatalogInterfaces.length" class="selected-interface-list">
              <div v-for="item in selectedCatalogInterfaces" :key="item.id" class="selected-interface-item">
                <div>
                  <strong>{{ item.name }}</strong>
                  <small>{{ selectedInterfaceFile(item) }}</small>
                </div>
                <button
                  class="selected-interface-remove"
                  type="button"
                  :aria-label="`移除 ${item.name}`"
                  :title="`移除 ${item.name}`"
                  @click="toggleCatalogInterface(item.id, false)"
                >
                  <X :size="14" />
                </button>
              </div>
            </div>
            <p v-else class="selected-interface-empty">从左侧选择本次需要扩展的接口</p>
          </div>

          <label class="field">
            <span>每个接口新增测试数</span>
            <input
              :value="testForm.testsPerInterface"
              type="number"
              min="1"
              :max="interfaceCatalog.max_tests_per_interface || 5"
              step="1"
              @input="clampTestsPerInterface"
            />
          </label>

          <label class="field">
            <span>补充要求（可选）</span>
            <textarea
              v-model="testForm.extraRequirements"
              rows="4"
              placeholder="例如：优先补充零值、负值和容差边界场景"
            ></textarea>
          </label>

          <div class="generated-target">
            <FileCode2 :size="17" />
            <div>
              <span>本次生成范围</span>
              <code>{{ catalogSelectionSummary.fileCount }} 个文件 · {{ catalogSelectionSummary.interfaceCount }} 个接口 · {{ catalogSelectionSummary.requestedTestCount }} 条测试</code>
            </div>
          </div>

          <div class="action-stack">
            <button class="primary-button" type="button" :disabled="!!busyAction || !selectedCatalogInterfaces.length" @click="createTestJob">
              <FlaskConical :size="16" />
              新建任务并生成
            </button>
            <button class="ghost-button" type="button" :disabled="!!busyAction || selectedJob?.active || !selectedJob?.worktree_path || !selectedCatalogInterfaces.length || selectedJob?.module !== testForm.module" @click="extendSelectedTestJob">
              <Repeat2 :size="16" />
              继续扩展选中任务
            </button>
          </div>
          <p v-if="selectedJob && selectedJob.module !== testForm.module" class="form-help">
            当前任务属于 {{ selectedJob.module }} 模块，不能用来继续扩展 {{ testForm.module }} 接口。
          </p>
        </section>
      </aside>
    </div>

    <div v-else class="review-workspace">
      <JobTable />

      <div class="review-control-grid">
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
                  复制
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

          <div class="filter-mode-control">
            <span>运行范围</span>
            <div class="segmented">
              <button
                type="button"
                :class="{ active: gtestFilterMode === 'suggested' }"
                :aria-pressed="gtestFilterMode === 'suggested'"
                @click="gtestFilterMode = 'suggested'"
              >
                建议范围
              </button>
              <button
                type="button"
                :class="{ active: gtestFilterMode === 'custom' }"
                :aria-pressed="gtestFilterMode === 'custom'"
                @click="gtestFilterMode = 'custom'"
              >
                自定义
              </button>
            </div>
          </div>

          <div v-if="gtestFilterMode === 'suggested'" class="suggested-filter">
            <ListChecks :size="17" />
            <div>
              <span>建议 Filter</span>
              <strong>{{ generatedTestInfo.filterSummary }}</strong>
            </div>
            <button class="ghost-button compact" type="button" @click="copyText(generatedTestInfo.filter)">
              <Clipboard :size="14" />
              复制
            </button>
          </div>

          <label v-else class="field custom-filter-field">
            <span>自定义 GTest Filter</span>
            <input v-model="testForm.gtestFilter" placeholder="例如：SuiteName.TestName；留空表示全部测试" />
          </label>

          <div class="action-row">
            <button class="ghost-button" type="button" :disabled="!!busyAction || !selectedJob || selectedJob.active" @click="buildSelectedJob">
              <Hammer :size="16" />
              构建
            </button>
            <button class="ghost-button" type="button" :disabled="!!busyAction || !selectedJob || selectedJob.active" @click="runSelectedTests">
              <Play :size="16" />
              运行测试
            </button>
          </div>

          <div class="action-row danger-row">
            <button class="danger-button" type="button" :disabled="!!busyAction || !selectedJob || selectedJob.active" @click="cleanupSelectedJob">
              <Trash2 :size="16" />
              清理工作区
            </button>
            <button class="danger-button" type="button" :disabled="!!busyAction || !selectedJob || selectedJob.active" @click="deleteSelectedJob">
              <Trash2 :size="16" />
              删除记录
            </button>
          </div>
        </section>
      </div>

      <ArtifactTabs />
    </div>
  </section>
</template>
