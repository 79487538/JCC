const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("screenshotAPI", {
  listSources: () => ipcRenderer.invoke("screenshot:list-sources"),
  captureSource: (sourceId) => ipcRenderer.invoke("screenshot:capture-source", sourceId),
});
