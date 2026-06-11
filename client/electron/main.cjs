const { app, BrowserWindow, desktopCapturer, ipcMain } = require("electron");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const createWindow = () => {
  const win = new BrowserWindow({
    width: 1180,
    height: 760,
    minWidth: 960,
    minHeight: 640,
    backgroundColor: "#111318",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.cjs"),
    },
  });

  const devServerUrl = process.env.VITE_DEV_SERVER_URL;
  if (devServerUrl) {
    win.loadURL(devServerUrl);
  } else {
    win.loadFile(path.join(__dirname, "../dist/index.html"));
  }
};

app.whenReady().then(() => {
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

ipcMain.handle("screenshot:list-sources", async () => {
  const sources = await desktopCapturer.getSources({
    types: ["window", "screen"],
    thumbnailSize: { width: 360, height: 220 },
    fetchWindowIcons: true,
  });

  return sources.map((source) => ({
    id: source.id,
    name: source.name,
    thumbnailDataUrl: source.thumbnail.toDataURL(),
  }));
});

ipcMain.handle("screenshot:capture-source", async (_event, sourceId) => {
  const sources = await desktopCapturer.getSources({
    types: ["window", "screen"],
    thumbnailSize: { width: 1920, height: 1080 },
    fetchWindowIcons: false,
  });
  const source = sources.find((item) => item.id === sourceId) || sources[0];
  if (!source) {
    throw new Error("No capturable screen or window source found");
  }

  const pngBuffer = source.thumbnail.toPNG();
  const filePath = path.join(
    os.tmpdir(),
    `jcc-s17-screenshot-${Date.now()}.png`,
  );
  fs.writeFileSync(filePath, pngBuffer);

  return {
    filePath,
    sourceId: source.id,
    sourceName: source.name,
    dataUrl: source.thumbnail.toDataURL(),
  };
});
