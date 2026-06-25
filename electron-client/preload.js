const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("jccApi", {
  analyzeMockScreenshot: () => ipcRenderer.invoke("analysis:mock-screenshot"),
  submitFeedback: (payload) => ipcRenderer.invoke("feedback:submit", payload),
});
