const API_BASE =
  import.meta.env.VITE_API_BASE_URL ||
  (window.location.protocol === "file:" ? "http://127.0.0.1:8765/api" : "/api");

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
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
  validate: () => request("/validate"),
  listJobs: () => request("/jobs"),
  getJob: (jobId) => request(`/jobs/${encodeURIComponent(jobId)}`),
  getJobEvents: (jobId) => request(`/jobs/${encodeURIComponent(jobId)}/events`),
  getJobArtifacts: (jobId) => request(`/jobs/${encodeURIComponent(jobId)}/artifacts`),
  createTestJob: (data) => request("/jobs/test-generation", { method: "POST", body: JSON.stringify(data) }),
  extendTestJob: (jobId, data) => request(`/jobs/${encodeURIComponent(jobId)}/extend-tests`, { method: "POST", body: JSON.stringify(data) }),
  buildJob: (jobId, data) => request(`/jobs/${encodeURIComponent(jobId)}/build`, { method: "POST", body: JSON.stringify(data) }),
  runTests: (jobId, data) => request(`/jobs/${encodeURIComponent(jobId)}/run-tests`, { method: "POST", body: JSON.stringify(data) }),
  createSkipPr: (jobId) => request(`/jobs/${encodeURIComponent(jobId)}/skip-pr`, { method: "POST", body: "{}" }),
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
  fixFailure: (failureId) => request(`/failures/${encodeURIComponent(failureId)}/fix`, { method: "POST", body: "{}" }),
  setFailureStatus: (failureId, status) =>
    request(`/failures/${encodeURIComponent(failureId)}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),
};
