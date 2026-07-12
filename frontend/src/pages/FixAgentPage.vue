<script setup>
import { computed, ref, watch } from "vue";
import { Ban, CheckCircle2, Clipboard, ExternalLink, ListChecks, Play, RotateCcw, Wrench } from "@lucide/vue";
import FailureTable from "../components/FailureTable.vue";
import MetricStrip from "../components/MetricStrip.vue";
import { useWorkspace } from "../composables/useWorkspace";

const {
  activePage,
  testWorkspaceTab,
  fixWorkspaceTab,
  busyAction,
  failureStats,
  jobs,
  fixJobs,
  selectedFailure,
  selectedFixJob,
  fixArtifacts,
  fixEventsText,
  fixDiffText,
  fixCodexText,
  failureFilter,
  copyText,
  fixSelectedFailure,
  reproduceSelectedFailure,
  markSelectedFailure,
  selectJob,
  selectFixJob,
  selectFailure,
  shortId,
  jobStatus,
  failureStatus,
  statusTone,
} = useWorkspace();

const activeFixResultTab = ref("changes");
const selectedFixDiffPath = ref("");

const selectedFullName = computed(() => {
  const failure = selectedFailure.value;
  return failure?.test_suite && failure?.test_name ? `${failure.test_suite}.${failure.test_name}` : "";
});

const sourceJob = computed(() => jobs.value.find((job) => job.id === selectedFailure.value?.job_id) || null);
const fixJob = computed(() => {
  const fixJobId = selectedFailure.value?.metadata?.fix_job_id;
  if (fixJobId) return jobs.value.find((job) => job.id === fixJobId) || null;
  if (selectedFixJob.value?.metadata?.failure_id === selectedFailure.value?.id) return selectedFixJob.value;
  return null;
});

const selectedFilter = computed(() => failureFilter(selectedFailure.value || {}));
const canCreateFix = computed(() => selectedFailure.value?.status === "open");
const canMarkFixed = computed(() => Boolean(
  selectedFailure.value
  && (selectedFailure.value.status === "fix_ready" || selectedFixJob.value?.metadata?.fix_validated),
));
const targetModulePath = computed(() => {
  const moduleName = sourceJob.value?.module || selectedFailure.value?.metadata?.module || selectedFixJob.value?.module || "";
  return moduleName ? `module/${moduleName}` : "module/<模块名>";
});
const fixDiffFiles = computed(() => parseDiffFiles(fixDiffText.value));
const selectedFixDiffFile = computed(() => fixDiffFiles.value.find((file) => file.path === selectedFixDiffPath.value) || fixDiffFiles.value[0] || null);
const fixVerifyOutput = computed(() => artifactContent(["gtest_verify_after_fix.txt", "gtest_output.txt"]));
const fixReproduceOutput = computed(() => artifactContent(["gtest_reproduce_before_fix.txt"]));
const fixBuildOutput = computed(() => artifactContent(["build_output.txt"]));
const hasFixArtifacts = computed(() => Boolean(
  selectedFixJob.value
  && (fixDiffText.value || fixEventsText.value || (fixArtifacts.value.files || []).length > 0),
));
const fixResultTabs = computed(() =>
  [
    { key: "changes", label: "代码变更", available: fixDiffFiles.value.length > 0 },
    { key: "verify", label: "修复后验证", available: Boolean(fixVerifyOutput.value) },
    { key: "reproduce", label: "修复前复现", available: Boolean(fixReproduceOutput.value) },
    { key: "build", label: "构建输出", available: Boolean(fixBuildOutput.value) },
    { key: "codex", label: "Codex 输出", available: Boolean(fixCodexText.value) },
    { key: "logs", label: "日志", available: Boolean(fixEventsText.value) },
  ].filter((tab) => tab.available || tab.key === "changes"),
);
const fixWorkflowSteps = computed(() => {
  const job = selectedFixJob.value;
  const done = [
    Boolean(job?.worktree_path),
    Boolean(fixReproduceOutput.value),
    Boolean(fixDiffText.value),
    Boolean(job?.metadata?.fix_validated || (fixDiffText.value && fixBuildOutput.value)),
    Boolean(job?.metadata?.fix_validated),
  ];
  const status = job?.status || "";
  let activeIndex = -1;
  if (status === "creating_worktree") activeIndex = 0;
  else if (["building", "running_tests"].includes(status)) activeIndex = done[1] ? (done[3] ? 4 : 3) : 1;
  else if (status === "running_codex") activeIndex = 2;
  const firstIncomplete = done.findIndex((value) => !value);
  const details = [
    job?.worktree_path || "等待创建修复工作区",
    done[1] ? "已确认目标测试在修复前失败" : "等待复现目标失败",
    done[2] ? "已生成 GME 源码修改" : "等待 Codex 修改源码",
    done[3] ? "修复源码已完成构建" : "等待构建修复源码",
    done[4] ? "目标测试已在修复后通过" : "等待验证目标测试",
  ];
  return ["准备 worktree", "复现失败", "Codex 修改源码", "CMake 构建", "验证目标测试"].map((label, index) => ({
    label,
    detail: details[index],
    state: done[index]
      ? "done"
      : status === "failed" && index === firstIncomplete
        ? "failed"
        : index === activeIndex
          ? "active"
          : "pending",
  }));
});

function shortPath(path) {
  const value = String(path || "").replace(/\\/g, "/");
  const marker = "/tests/gme/";
  const index = value.lastIndexOf(marker);
  return index >= 0 ? value.slice(index + marker.length) : value.split("/").slice(-4).join("/");
}

function cleanReason(reason) {
  return String(reason || "暂无失败原因").replace(/\n{3,}/g, "\n\n").trim();
}

function shortFailureId(id) {
  const value = String(id || "");
  return value.startsWith("gmefail-") ? `gmefail-${value.slice(-8)}` : shortId(value);
}

function fixJobTestName(job) {
  const metadata = job?.metadata || {};
  if (metadata.test_suite && metadata.test_name) return `${metadata.test_suite}.${metadata.test_name}`;
  return metadata.gtest_filter || metadata.failure_id || "-";
}

function artifactContent(names) {
  const contents = fixArtifacts.value.contents || {};
  for (const name of names) {
    if (contents[name]) return contents[name];
  }
  return "";
}

function normalizePath(path) {
  return String(path || "").replace(/\\/g, "/").replace(/^\.\//, "");
}

function parseDiffFiles(diff) {
  const files = [];
  let current = null;
  for (const line of String(diff || "").split(/\r?\n/)) {
    const match = /^diff --git a\/(.+?) b\/(.+)$/.exec(line);
    if (match) {
      current = {
        path: normalizePath(match[2]),
        additions: 0,
        deletions: 0,
        rawLines: [line],
      };
      files.push(current);
      continue;
    }
    if (!current) continue;
    current.rawLines.push(line);
    if (line.startsWith("+") && !line.startsWith("+++")) current.additions += 1;
    if (line.startsWith("-") && !line.startsWith("---")) current.deletions += 1;
  }
  return files.map((file) => ({
    path: file.path,
    additions: file.additions,
    deletions: file.deletions,
    raw: file.rawLines.join("\n"),
  }));
}

async function openSourceJob() {
  if (!sourceJob.value) return;
  await selectJob(sourceJob.value.id);
  testWorkspaceTab.value = "review";
  activePage.value = "test";
}

async function showFixReview() {
  fixWorkspaceTab.value = "review";
  const job = selectedFixJob.value || fixJobs.value[0] || null;
  const failureId = job?.metadata?.failure_id;
  if (failureId) selectFailure(failureId);
  if (job) await selectFixJob(job.id);
}

async function openFixJob() {
  if (!fixJob.value) return;
  const failureId = fixJob.value.metadata?.failure_id;
  if (failureId) selectFailure(failureId);
  await selectFixJob(fixJob.value.id);
  fixWorkspaceTab.value = "review";
  activeFixResultTab.value = "changes";
}

async function openFixJobFromRow(job) {
  const failureId = job?.metadata?.failure_id;
  if (failureId) selectFailure(failureId);
  await selectFixJob(job.id);
  fixWorkspaceTab.value = "review";
  activeFixResultTab.value = "changes";
}

watch(
  fixDiffFiles,
  (files) => {
    if (!files.length) {
      selectedFixDiffPath.value = "";
      return;
    }
    if (!files.some((file) => file.path === selectedFixDiffPath.value)) {
      selectedFixDiffPath.value = files[0].path;
    }
  },
  { immediate: true },
);

watch(hasFixArtifacts, (loaded) => {
  if (loaded) activeFixResultTab.value = fixDiffFiles.value.length ? "changes" : "verify";
});

watch(
  fixResultTabs,
  (tabs) => {
    if (!tabs.some((tab) => tab.key === activeFixResultTab.value)) {
      activeFixResultTab.value = tabs[0]?.key || "changes";
    }
  },
  { immediate: true },
);
</script>

<template>
  <section class="page fix-page">
    <div class="page-heading">
      <div>
        <span class="eyebrow">Fix Agent</span>
        <h1>修复 Agent</h1>
      </div>
      <MetricStrip
        :items="[
          { label: '未修复', value: failureStats.open },
          { label: '处理中', value: failureStats.fixing },
          { label: '已修复', value: failureStats.fixed },
        ]"
      />
    </div>

    <nav class="workspace-tabs" role="tablist" aria-label="修复 Agent 工作视图">
      <button
        type="button"
        role="tab"
        :aria-selected="fixWorkspaceTab === 'select'"
        :class="{ active: fixWorkspaceTab === 'select' }"
        @click="fixWorkspaceTab = 'select'"
      >
        <Wrench :size="17" />
        <span>选择失败</span>
        <small v-if="failureStats.open">{{ failureStats.open }}</small>
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="fixWorkspaceTab === 'review'"
        :class="{ active: fixWorkspaceTab === 'review' }"
        @click="showFixReview"
      >
        <ListChecks :size="17" />
        <span>任务与结果</span>
        <small v-if="fixJobs.length">{{ fixJobs.length }}</small>
      </button>
    </nav>

    <div v-if="fixWorkspaceTab === 'select'" class="fix-layout refined fix-selection-layout">
      <FailureTable />

      <section class="panel fix-detail-panel">
        <div v-if="selectedFailure" class="fix-detail">
          <div class="fix-detail-header">
            <div>
              <span class="eyebrow">选中失败</span>
              <h2>{{ selectedFullName }}</h2>
              <div class="detail-meta">
                <span class="status-pill" :class="statusTone(selectedFailure.status)">{{ failureStatus(selectedFailure) }}</span>
                <code>{{ shortFailureId(selectedFailure.id) }}</code>
              </div>
            </div>
            <div class="fix-primary-actions">
              <button class="primary-button" type="button" :disabled="!!busyAction || !canCreateFix" @click="fixSelectedFailure">
                <Wrench :size="16" />
                创建修复任务
              </button>
              <button class="ghost-button" type="button" :disabled="!!busyAction" @click="reproduceSelectedFailure">
                <Play :size="16" />
                复现
              </button>
            </div>
          </div>

          <div class="fix-info-grid">
            <div>
              <span>模块</span>
              <strong>{{ sourceJob?.module || selectedFailure.metadata?.module || "-" }}</strong>
            </div>
            <div>
              <span>测试文件</span>
              <strong>{{ shortPath(selectedFailure.file) || "-" }}</strong>
            </div>
            <div>
              <span>行号</span>
              <strong>{{ selectedFailure.line || "-" }}</strong>
            </div>
            <div>
              <span>修复范围</span>
              <strong>{{ targetModulePath }}</strong>
            </div>
          </div>

          <div class="fix-section">
            <h3>失败原因</h3>
            <pre class="reason-box">{{ cleanReason(selectedFailure.reason) }}</pre>
          </div>

          <div class="fix-section">
            <div class="fix-section-title">
              <h3>目标 GTest Filter</h3>
              <button class="ghost-button compact" type="button" @click="copyText(selectedFilter)">
                <Clipboard :size="14" />
                复制
              </button>
            </div>
            <code class="filter-box">{{ selectedFilter }}</code>
          </div>

          <article class="task-card">
            <span>关联修复任务</span>
            <strong>{{ fixJob ? shortId(fixJob.id) : "尚未创建" }}</strong>
            <small>{{ fixJob ? jobStatus(fixJob) : "创建后会自动进入结果页" }}</small>
            <button class="ghost-button compact" type="button" :disabled="!fixJob" @click="openFixJob">
              <ExternalLink :size="14" />
              查看结果
            </button>
          </article>
        </div>

        <div v-else class="empty-state large">
          <strong>先选择一个失败用例</strong>
          <span>左侧列表会显示测试 Agent 记录的最新失败。</span>
        </div>
      </section>
    </div>

    <div v-else class="fix-review-workspace">
      <section class="panel table-panel fix-job-panel">
        <div class="panel-title-row">
          <h2>修复任务</h2>
          <span class="mini-badge">{{ fixJobs.length }} 个</span>
        </div>
        <div class="table-wrap">
          <table class="data-table fix-job-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>状态</th>
                <th>失败用例</th>
                <th>模块</th>
                <th>来源任务</th>
                <th>更新时间</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="job in fixJobs"
                :key="job.id"
                :class="{ selected: selectedFixJob?.id === job.id }"
                @click="openFixJobFromRow(job)"
              >
                <td><code>{{ shortId(job.id) }}</code></td>
                <td><span class="status-pill" :class="statusTone(job.status)">{{ jobStatus(job) }}</span></td>
                <td class="truncate">{{ fixJobTestName(job) }}</td>
                <td>{{ job.module || "-" }}</td>
                <td><code>{{ shortId(job.metadata?.source_job_id) }}</code></td>
                <td>{{ job.updated_at }}</td>
              </tr>
              <tr v-if="!fixJobs.length">
                <td colspan="6" class="empty-cell">暂无修复任务</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <div class="fix-review-control-grid">
        <section class="panel current-fix-job-panel">
          <div class="panel-title-row">
            <h2>当前修复任务</h2>
            <span v-if="selectedFixJob" class="status-pill" :class="statusTone(selectedFixJob.status)">{{ jobStatus(selectedFixJob) }}</span>
          </div>

          <template v-if="selectedFixJob">
            <div class="fix-info-grid">
              <div>
                <span>ID</span>
                <strong>{{ shortId(selectedFixJob.id) }}</strong>
              </div>
              <div>
                <span>失败用例</span>
                <strong>{{ fixJobTestName(selectedFixJob) }}</strong>
              </div>
              <div>
                <span>模块</span>
                <strong>{{ selectedFixJob.module || "-" }}</strong>
              </div>
              <div>
                <span>修复范围</span>
                <strong>module/{{ selectedFixJob.module || "-" }}</strong>
              </div>
            </div>

            <div class="workflow fix-workflow">
              <div v-for="step in fixWorkflowSteps" :key="step.label" class="workflow-step" :class="step.state">
                <span class="step-dot"></span>
                <div>
                  <strong>{{ step.label }}</strong>
                  <small>{{ step.detail }}</small>
                </div>
              </div>
            </div>
          </template>
          <div v-else class="empty-state compact-empty">
            <strong>请选择修复任务</strong>
            <span>从上方任务表选择一条记录查看修复过程。</span>
          </div>
        </section>

        <section class="panel fix-review-actions-panel">
          <div class="panel-title-row">
            <h2>审查操作</h2>
            <span v-if="selectedFailure" class="status-pill" :class="statusTone(selectedFailure.status)">{{ failureStatus(selectedFailure) }}</span>
          </div>

          <template v-if="selectedFailure">
            <div class="review-failure-summary">
              <span>关联失败用例</span>
              <strong>{{ selectedFullName }}</strong>
              <small>{{ shortPath(selectedFailure.file) }}{{ selectedFailure.line ? `:${selectedFailure.line}` : "" }}</small>
            </div>

            <div class="action-stack">
              <button class="success-button" type="button" :disabled="!!busyAction || !canMarkFixed" @click="markSelectedFailure('fixed')">
                <CheckCircle2 :size="16" />
                确认已修复
              </button>
              <button class="ghost-button" type="button" :disabled="!!busyAction || !sourceJob" @click="openSourceJob">
                <ExternalLink :size="16" />
                打开来源测试任务
              </button>
              <button class="ghost-button" type="button" :disabled="!!busyAction" @click="markSelectedFailure('ignored')">
                <Ban :size="16" />
                标记忽略
              </button>
              <button class="ghost-button" type="button" :disabled="!!busyAction || selectedFailure.status === 'open'" @click="markSelectedFailure('open')">
                <RotateCcw :size="16" />
                重新打开
              </button>
            </div>
          </template>
          <div v-else class="empty-state compact-empty">
            <strong>没有关联失败</strong>
            <span>选择修复任务后会显示对应审查操作。</span>
          </div>
        </section>
      </div>

      <section class="panel fix-review-result-panel">
        <div class="fix-result-header">
          <div>
            <h2>修复结果</h2>
            <span>{{ selectedFixJob ? jobStatus(selectedFixJob) : "等待选择修复任务" }}</span>
          </div>
          <span v-if="selectedFixJob" class="mini-badge">{{ shortId(selectedFixJob.id) }}</span>
        </div>

        <div v-if="!selectedFixJob" class="empty-state compact-empty">
          <strong>请选择修复任务</strong>
          <span>代码变更和验证输出会显示在这里。</span>
        </div>
        <div v-else-if="!hasFixArtifacts" class="empty-state compact-empty">
          <strong>暂无修复产物</strong>
          <span>任务还在运行，稍后刷新即可看到 diff 和测试输出。</span>
        </div>
        <template v-else>
          <div class="fix-result-tabs">
            <button
              v-for="tab in fixResultTabs"
              :key="tab.key"
              type="button"
              :class="{ active: activeFixResultTab === tab.key }"
              @click="activeFixResultTab = tab.key"
            >
              {{ tab.label }}
            </button>
          </div>

          <div class="fix-result-body">
            <div v-if="activeFixResultTab === 'changes'">
              <div v-if="fixDiffFiles.length" class="fix-diff-layout">
                <div class="fix-diff-files">
                  <button
                    v-for="file in fixDiffFiles"
                    :key="file.path"
                    type="button"
                    :class="{ active: selectedFixDiffFile?.path === file.path }"
                    @click="selectedFixDiffPath = file.path"
                  >
                    <strong>{{ file.path }}</strong>
                    <span>+{{ file.additions }} / -{{ file.deletions }}</span>
                  </button>
                </div>
                <div class="fix-diff-detail">
                  <div class="fix-diff-heading">
                    <strong>{{ selectedFixDiffFile?.path }}</strong>
                    <span>新增 {{ selectedFixDiffFile?.additions || 0 }} 行，删除 {{ selectedFixDiffFile?.deletions || 0 }} 行</span>
                  </div>
                  <pre class="code-block fix-code-block">{{ selectedFixDiffFile?.raw || "暂无代码变更" }}</pre>
                </div>
              </div>
              <div v-else class="empty-state compact-empty">
                <strong>没有代码变更</strong>
                <span>当前修复任务没有生成 diff.patch。</span>
              </div>
            </div>
            <pre v-else-if="activeFixResultTab === 'verify'" class="code-block fix-code-block">{{ fixVerifyOutput || "暂无修复后验证输出" }}</pre>
            <pre v-else-if="activeFixResultTab === 'reproduce'" class="code-block fix-code-block">{{ fixReproduceOutput || "暂无修复前复现输出" }}</pre>
            <pre v-else-if="activeFixResultTab === 'build'" class="code-block fix-code-block">{{ fixBuildOutput || "暂无构建输出" }}</pre>
            <pre v-else-if="activeFixResultTab === 'codex'" class="code-block fix-code-block">{{ fixCodexText || "暂无 Codex 输出" }}</pre>
            <pre v-else class="code-block fix-code-block">{{ fixEventsText || "暂无日志" }}</pre>
          </div>
        </template>
      </section>
    </div>
  </section>
</template>
