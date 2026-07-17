const API_BASE =
  import.meta.env.VITE_API_BASE_URL ||
  (window.location.protocol === "file:" ? "http://127.0.0.1:8765/api" : "/api");

async function request(path, options = {}) {
  const apiToken = window.gmeAgent?.apiToken || import.meta.env.VITE_API_TOKEN || "";
  if (!apiToken) {
    throw new Error("缺少 GME Test Agent API Token，请通过桌面应用或 scripts/run_web.ps1 启动。");
  }
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
      Authorization: `Bearer ${apiToken}`,
    },
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(data.error || response.statusText);
  }
  return data;
}

export const api = {
  health: () => request("/health"),
  getConfig: () => request("/config"),
  saveConfig: (data) => request("/config", { method: "POST", body: JSON.stringify(data) }),
  getOptions: () => request("/options"),
  getModels: () => request("/models"),
  listInterfaceCatalogs: () => request("/interface-catalogs"),
  getInterfaceCatalog: (module) => request(`/interface-catalogs/${encodeURIComponent(module)}`),
  validate: () => request("/validate"),
  listJobs: () => request("/jobs"),
  getJob: (jobId) => request(`/jobs/${encodeURIComponent(jobId)}`),
  getJobEvents: (jobId) => request(`/jobs/${encodeURIComponent(jobId)}/events`),
  getJobArtifacts: (jobId) => request(`/jobs/${encodeURIComponent(jobId)}/artifacts`),
  getJobTestResults: (jobId) => request(`/jobs/${encodeURIComponent(jobId)}/test-results`),
  createTestJob: (data) => request("/jobs/test-generation", { method: "POST", body: JSON.stringify(data) }),
  extendTestJob: (jobId, data) => request(`/jobs/${encodeURIComponent(jobId)}/extend-tests`, { method: "POST", body: JSON.stringify(data) }),
  buildJob: (jobId, data) => request(`/jobs/${encodeURIComponent(jobId)}/build`, { method: "POST", body: JSON.stringify(data) }),
  runTests: (jobId, data) => request(`/jobs/${encodeURIComponent(jobId)}/run-tests`, { method: "POST", body: JSON.stringify(data) }),
  createSelectedTestsPr: (jobId, tests) =>
    request(`/jobs/${encodeURIComponent(jobId)}/selected-tests-pr`, {
      method: "POST",
      body: JSON.stringify({ tests }),
    }),
  deleteGeneratedTests: (jobId, tests) =>
    request(`/jobs/${encodeURIComponent(jobId)}/generated-tests/remove`, {
      method: "POST",
      body: JSON.stringify({ tests }),
    }),
  cleanupJob: (jobId) => request(`/jobs/${encodeURIComponent(jobId)}/cleanup`, { method: "POST", body: "{}" }),
  deleteJob: (jobId, data) =>
    request(`/jobs/${encodeURIComponent(jobId)}/delete`, {
      method: "POST",
      body: JSON.stringify(data || { cleanup_worktree: true, delete_artifacts: true }),
    }),
  listFailures: () => request("/failures"),
  getFailure: (failureId) => request(`/failures/${encodeURIComponent(failureId)}`),
  getFailureObservations: (failureId) => request(`/failures/${encodeURIComponent(failureId)}/observations`),
  fixFailure: (failureId) => request(`/failures/${encodeURIComponent(failureId)}/fix`, { method: "POST", body: "{}" }),
  setFailureStatus: (failureId, status) =>
    request(`/failures/${encodeURIComponent(failureId)}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),
};
