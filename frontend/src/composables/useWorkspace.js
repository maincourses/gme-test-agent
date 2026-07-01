import { computed, reactive, ref } from "vue";
import { api } from "../api";

export const jobTypeLabels = {
  test_generation: "生成测试",
  bug_fix: "修复缺陷",
};

export const jobStatusLabels = {
  queued: "排队中",
  creating_worktree: "创建工作区",
  running_codex: "调用 Codex",
  building: "构建中",
  running_tests: "测试中",
  applying_skips: "添加 skip",
  creating_pr: "创建 PR",
  cleaning_worktree: "清理工作区",
  needs_review: "待审查",
  failed: "失败",
  pr_created: "PR 已创建",
  worktree_cleaned: "工作区已清理",
};

export const failureStatusLabels = {
  open: "未修复",
  fixing: "修复中",
  fix_ready: "待审查",
  fixed: "已修复",
  ignored: "已忽略",
  fix_failed: "修复失败",
};

const activePage = ref("test");
const activeJobTab = ref("logs");
const loading = ref(false);
const busyAction = ref("");
const error = ref("");
const notice = ref("");
const backendOk = ref(false);
const validation = ref(null);
const jobs = ref([]);
const failures = ref([]);
const events = ref([]);
const artifacts = ref({ artifact_dir: "", files: [], contents: {} });
const selectedJobId = ref("");
const selectedFailureId = ref("");

const configOptions = ref({
  branches: [],
  remotes: [],
  modules: [],
  sandbox_options: ["workspace-write", "read-only", "danger-full-access"],
  approval_policy_options: ["never", "auto_review"],
});

const configForm = reactive({
  gme_repo_path: "",
  worktree_root: "",
  artifact_root: "",
  database_path: "",
  base_branch: "",
  github_remote: "",
  model: "",
  sandbox: "",
  approval_policy: "",
  initialize_submodules: false,
  test_target_repo: "",
  module_repo_root: "",
  pr_strategy: "",
  use_builtin_skills: true,
  test_generation_skill: "",
  bug_fix_skill: "",
  configure_command: "",
  build_command: "",
  test_command: "",
  test_executable: "",
  gtest_xml_path: "",
  codex_enabled: true,
  auto_run_build: false,
  auto_run_tests: false,
  auto_apply_skips: false,
  auto_rerun_after_skip: false,
  auto_create_pr: false,
});

const testForm = reactive({
  module: "laws",
  apiName: "",
  gtestFilter: "*",
});

function failureTimestamp(failure) {
  return failure?.updated_at || failure?.created_at || "";
}

function realFailureKey(failure) {
  return [failure?.job_id || "", failure?.test_suite || "", failure?.test_name || ""].join("\x1f");
}

function latestRealFailures(items) {
  const latest = new Map();
  for (const failure of items || []) {
    const key = realFailureKey(failure);
    const current = latest.get(key);
    if (!current || failureTimestamp(failure) > failureTimestamp(current)) {
      latest.set(key, failure);
    }
  }
  return Array.from(latest.values()).sort((left, right) => failureTimestamp(right).localeCompare(failureTimestamp(left)));
}

const selectedJob = computed(() => jobs.value.find((job) => job.id === selectedJobId.value) || null);
const currentFailures = computed(() => latestRealFailures(failures.value));
const selectedFailure = computed(() => currentFailures.value.find((failure) => failure.id === selectedFailureId.value) || failures.value.find((failure) => failure.id === selectedFailureId.value) || null);
const selectedJobFailures = computed(() => currentFailures.value.filter((failure) => failure.job_id === selectedJobId.value));
const selectedJobOpenFailures = computed(() => selectedJobFailures.value.filter((failure) => failure.status === "open"));
const eventsText = computed(() => events.value.map((event) => `[${event.ts}] ${event.level}: ${event.message}`).join("\n"));
const diffText = computed(() => artifacts.value.contents?.["diff.patch"] || "");
const codexText = computed(
  () => artifacts.value.contents?.["codex_skip_result.txt"] || artifacts.value.contents?.["codex_extend_result.txt"] || artifacts.value.contents?.["codex_result.txt"] || "",
);
const agentNotesText = computed(() => {
  const contents = artifacts.value.contents || {};
  return Object.keys(contents)
    .filter((name) => name.startsWith(".gme-agent/"))
    .sort()
    .map((name) => `# ${name}\n\n${contents[name]}`)
    .join("\n\n");
});
const jobDetailJson = computed(() =>
  JSON.stringify(
    {
      job: selectedJob.value,
      failures: selectedJobFailures.value,
      artifacts: artifacts.value.files || [],
      artifact_dir: artifacts.value.artifact_dir || "",
    },
    null,
    2,
  ),
);
const failureDetailJson = computed(() => JSON.stringify({ failure: selectedFailure.value }, null, 2));
const selectedJobModule = computed(() => selectedJob.value?.module || testForm.module || "");
const generatedTestInfo = computed(() => {
  const moduleName = String(selectedJobModule.value || "module").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
  const moduleToken = moduleName.split("/").filter(Boolean).join("_") || "module";
  const modulePrefix = moduleToken
    .split("_")
    .filter(Boolean)
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join("");
  const suite = `${modulePrefix}_GmeAgentGeneratedTest`;
  return {
    file: `tests/gme/src/${moduleName}/gme_agent_${moduleToken}_generated_test.cpp`,
    filter: `${suite}.*`,
    suite,
  };
});
const workflowSteps = computed(() => {
  const job = selectedJob.value;
  const fileNames = new Set((artifacts.value.files || []).map((file) => file.name));
  const steps = [
    {
      label: "准备 worktree",
      detail: job?.worktree_path || "等待创建任务",
      state: stepState(job, "creating_worktree", Boolean(job?.worktree_path)),
    },
    {
      label: "Codex 生成测试",
      detail: generatedTestInfo.value.file,
      state: stepState(job, "running_codex", Boolean(job?.codex_thread_id || fileNames.has("codex_result.txt") || fileNames.has("codex_extend_result.txt"))),
    },
    {
      label: "CMake 构建",
      detail: "构建 tests 目标",
      state: stepState(job, "building", fileNames.has("build_output.txt")),
    },
    {
      label: "GTest 运行",
      detail: testForm.gtestFilter || generatedTestInfo.value.filter,
      state: stepState(job, "running_tests", fileNames.has("gtest_output.txt")),
    },
    {
      label: "失败用例加 skip",
      detail: "对当前最新失败写入 GTEST_SKIP",
      state: stepState(job, "applying_skips", fileNames.has("codex_skip_result.txt") || fileNames.has("gtest_output_after_skip.txt")),
    },
    {
      label: "创建 skip PR",
      detail: job?.metadata?.skip_pr_url || job?.metadata?.pr_url || "生成 PR",
      state: stepState(job, "creating_pr", job?.status === "pr_created"),
    },
  ];
  if (job?.status === "failed") {
    const failedIndex = steps.findIndex((step) => step.state !== "done");
    if (failedIndex >= 0) {
      steps[failedIndex] = { ...steps[failedIndex], state: "failed" };
    }
  }
  return steps;
});

const jobStats = computed(() => ({
  total: jobs.value.length,
  running: jobs.value.filter((job) => ["creating_worktree", "running_codex", "building", "running_tests", "applying_skips", "creating_pr"].includes(job.status)).length,
  review: jobs.value.filter((job) => job.status === "needs_review").length,
  failed: jobs.value.filter((job) => job.status === "failed").length,
}));

const failureStats = computed(() => ({
  total: currentFailures.value.length,
  open: currentFailures.value.filter((failure) => failure.status === "open").length,
  fixing: currentFailures.value.filter((failure) => ["fixing", "fix_ready"].includes(failure.status)).length,
  fixed: currentFailures.value.filter((failure) => failure.status === "fixed").length,
}));

const branchOptions = computed(() => withCurrent(configOptions.value.branches, configForm.base_branch));
const remoteOptions = computed(() => withCurrent(configOptions.value.remotes, configForm.github_remote));
const moduleOptions = computed(() => withCurrent(configOptions.value.modules, testForm.module));
const sandboxOptions = computed(() => withCurrent(configOptions.value.sandbox_options, configForm.sandbox));
const approvalPolicyOptions = computed(() => withCurrent(configOptions.value.approval_policy_options, configForm.approval_policy));

let noticeTimer = null;

export function useWorkspace() {
  return {
    activePage,
    activeJobTab,
    loading,
    busyAction,
    error,
    notice,
    backendOk,
    validation,
    configOptions,
    configForm,
    testForm,
    jobs,
    failures,
    currentFailures,
    events,
    artifacts,
    selectedJobId,
    selectedFailureId,
    selectedJob,
    selectedFailure,
    selectedJobFailures,
    selectedJobOpenFailures,
    eventsText,
    diffText,
    codexText,
    agentNotesText,
    jobDetailJson,
    failureDetailJson,
    generatedTestInfo,
    workflowSteps,
    jobStats,
    failureStats,
    branchOptions,
    remoteOptions,
    moduleOptions,
    sandboxOptions,
    approvalPolicyOptions,
    refreshAll,
    refreshRuntime,
    loadSelectedJobData,
    selectJob,
    selectFailure,
    saveConfig,
    chooseDirectory,
    chooseFile,
    validateEnvironment,
    createTestJob,
    extendSelectedTestJob,
    buildSelectedJob,
    runSelectedTests,
    createSkipPrForSelectedJob,
    cleanupSelectedJob,
    deleteSelectedJob,
    fixSelectedFailure,
    reproduceSelectedFailure,
    markSelectedFailure,
    failureFilter,
    shortId,
    jobStatus,
    failureStatus,
    statusTone,
    copyText,
    openPr,
    setError,
  };
}

async function refreshAll() {
  loading.value = true;
  try {
    await loadConfig();
    await loadConfigOptions();
    await refreshRuntime(true);
    backendOk.value = true;
  } catch (err) {
    backendOk.value = false;
    setError(err);
  } finally {
    loading.value = false;
  }
}

async function refreshRuntime(silent = false) {
  if (!silent) loading.value = true;
  try {
    const [jobsData, failuresData] = await Promise.all([api.listJobs(), api.listFailures()]);
    jobs.value = jobsData.jobs || [];
    failures.value = failuresData.failures || [];
    const selectableFailures = latestRealFailures(failures.value);
    if (selectedJobId.value && !jobs.value.some((job) => job.id === selectedJobId.value)) selectedJobId.value = "";
    if (!selectedJobId.value && jobs.value.length) selectedJobId.value = jobs.value[0].id;
    if (selectedFailureId.value && !selectableFailures.some((failure) => failure.id === selectedFailureId.value)) selectedFailureId.value = "";
    if (!selectedFailureId.value && selectableFailures.length) selectedFailureId.value = selectableFailures[0].id;
    await loadSelectedJobData();
    backendOk.value = true;
  } catch (err) {
    backendOk.value = false;
    if (!silent) setError(err);
  } finally {
    if (!silent) loading.value = false;
  }
}

async function loadConfig() {
  Object.assign(configForm, await api.getConfig());
}

async function loadConfigOptions() {
  try {
    configOptions.value = { ...configOptions.value, ...(await api.getOptions()) };
  } catch (err) {
    setError(err);
  }
}

async function loadSelectedJobData() {
  if (!selectedJobId.value) {
    events.value = [];
    artifacts.value = { artifact_dir: "", files: [], contents: {} };
    return;
  }
  const [eventsData, artifactsData] = await Promise.all([
    api.getJobEvents(selectedJobId.value),
    api.getJobArtifacts(selectedJobId.value),
  ]);
  events.value = eventsData.events || [];
  artifacts.value = artifactsData || { artifact_dir: "", files: [], contents: {} };
}

async function selectJob(jobId) {
  selectedJobId.value = jobId;
  await loadSelectedJobData();
}

function selectFailure(failureId) {
  selectedFailureId.value = failureId;
}

async function saveConfig() {
  await runAction("保存配置", async () => {
    Object.assign(configForm, await api.saveConfig({ ...configForm }));
    await loadConfigOptions();
  });
}

async function chooseDirectory(field) {
  if (!window.gmeAgent?.selectDirectory) {
    setError("当前浏览器模式不支持系统目录选择，请使用 Electron exe。");
    return;
  }
  const selected = await window.gmeAgent.selectDirectory(configForm[field] || "");
  if (selected) configForm[field] = selected;
}

async function chooseFile(field, filters = []) {
  if (!window.gmeAgent?.selectFile) {
    setError("当前浏览器模式不支持系统文件选择，请使用 Electron exe。");
    return;
  }
  const selected = await window.gmeAgent.selectFile(configForm[field] || "", filters);
  if (selected) configForm[field] = selected;
}

async function validateEnvironment() {
  await runAction("环境检查", async () => {
    validation.value = await api.validate();
    activePage.value = "config";
  });
}

async function createTestJob() {
  await runAction("生成测试", async () => {
    const job = await api.createTestJob({
      module: testForm.module || "gme",
      api_name: testForm.apiName,
    });
    selectedJobId.value = job.id;
    activePage.value = "test";
  });
}

async function extendSelectedTestJob() {
  await withSelectedJob("继续扩展测试", async (job) => {
    if (job.type !== "test_generation") {
      throw new Error("只能继续扩展测试生成任务。");
    }
    if (!job.worktree_path) {
      throw new Error("选中任务还没有工作区，不能继续扩展。");
    }
    await api.extendTestJob(job.id, {
      api_name: testForm.apiName,
    });
  });
}

async function buildSelectedJob() {
  await withSelectedJob("构建选中任务", (job) => api.buildJob(job.id));
}

async function runSelectedTests() {
  await withSelectedJob("运行选中测试", (job) =>
    api.runTests(job.id, {
      gtest_filter: testForm.gtestFilter || "*",
    }),
  );
}

async function createSkipPrForSelectedJob() {
  await withSelectedJob("加 skip 并创建 PR", (job) => {
    if (!selectedJobOpenFailures.value.length) {
      throw new Error("当前任务没有最新未处理失败用例。");
    }
    return api.createSkipPr(job.id);
  });
}

async function cleanupSelectedJob() {
  if (!selectedJob.value) {
    setError("请先选择一个任务。");
    return;
  }
  if (!window.confirm("确定要清理选中任务的工作区吗？")) return;
  await withSelectedJob("清理工作区", (job) => api.cleanupJob(job.id));
}

async function deleteSelectedJob() {
  const job = selectedJob.value;
  if (!job) {
    setError("请先选择一个任务。");
    return;
  }
  if (!window.confirm("确定要删除选中任务记录吗？会同时清理该任务的工作区和产物目录，此操作不可恢复。")) return;
  await runAction("删除任务记录", async () => {
    await api.deleteJob(job.id, { cleanup_worktree: true, delete_artifacts: true });
    selectedJobId.value = "";
    selectedFailureId.value = "";
  });
}

async function fixSelectedFailure() {
  if (!selectedFailure.value) {
    setError("请先选择一个失败用例。");
    return;
  }
  await runAction("修复选中失败", async () => {
    const job = await api.fixFailure(selectedFailure.value.id);
    selectedJobId.value = job.id;
    activePage.value = "test";
  });
}

async function reproduceSelectedFailure() {
  const failure = selectedFailure.value;
  if (!failure) {
    setError("请先选择一个失败用例。");
    return;
  }
  if (!failure.job_id) {
    setError("这个失败用例没有关联任务。");
    return;
  }
  const filter = failureFilter(failure);
  testForm.gtestFilter = filter;
  selectedJobId.value = failure.job_id;
  activePage.value = "test";
  await runAction("复现失败", () => api.runTests(failure.job_id, { gtest_filter: filter }));
}

async function markSelectedFailure(status) {
  if (!selectedFailure.value) {
    setError("请先选择一个失败用例。");
    return;
  }
  await runAction(`标记为${failureStatusLabels[status] || status}`, () => api.setFailureStatus(selectedFailure.value.id, status));
}

async function withSelectedJob(label, action) {
  if (!selectedJob.value) {
    setError("请先选择一个任务。");
    return;
  }
  await runAction(label, () => action(selectedJob.value));
}

async function runAction(label, action) {
  busyAction.value = label;
  error.value = "";
  try {
    await action();
    setNotice(`${label}已提交`);
    await refreshRuntime(true);
  } catch (err) {
    setError(err);
  } finally {
    busyAction.value = "";
  }
}

function failureFilter(failure) {
  return failure?.test_suite && failure?.test_name ? `${failure.test_suite}.${failure.test_name}` : "*";
}

function withCurrent(values, current) {
  const seen = new Set();
  const result = [];
  for (const value of [current, ...(values || [])]) {
    const item = String(value || "").trim();
    if (!item || seen.has(item)) continue;
    seen.add(item);
    result.push(item);
  }
  return result;
}

function shortId(id) {
  return id ? id.slice(0, 8) : "";
}

function jobStatus(job) {
  return jobStatusLabels[job.status] || job.status;
}

function failureStatus(failure) {
  return failureStatusLabels[failure.status] || failure.status;
}

function statusTone(status) {
  if (["failed", "fix_failed"].includes(status)) return "danger";
  if (["needs_review", "fix_ready", "open"].includes(status)) return "warning";
  if (["pr_created", "fixed", "worktree_cleaned"].includes(status)) return "success";
  if (["running_codex", "building", "running_tests", "fixing", "creating_pr", "applying_skips"].includes(status)) return "info";
  return "neutral";
}

function stepState(job, activeStatus, done) {
  if (!job) return "pending";
  if (job.status === activeStatus) return "active";
  return done ? "done" : "pending";
}

async function copyText(text) {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    setNotice("已复制");
  } catch {
    setError("复制失败，请手动选择文本。");
  }
}

function openPr() {
  const url = selectedJob.value?.metadata?.pr_url;
  if (!url) {
    setError("选中任务还没有 PR 链接。");
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

function setNotice(message) {
  notice.value = message;
  if (noticeTimer) window.clearTimeout(noticeTimer);
  noticeTimer = window.setTimeout(() => {
    notice.value = "";
  }, 3000);
}

function setError(err) {
  error.value = err?.message || String(err);
}
