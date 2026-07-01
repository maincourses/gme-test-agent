const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("gmeAgent", {
  selectDirectory: (currentPath) => ipcRenderer.invoke("gme-agent:select-directory", currentPath || ""),
  selectFile: (currentPath, filters) => ipcRenderer.invoke("gme-agent:select-file", currentPath || "", filters || []),
});
