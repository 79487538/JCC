const { app, BrowserWindow, ipcMain } = require("electron");
const fs = require("fs");
const path = require("path");

function loadDotEnv() {
  const envPath = path.join(__dirname, "..", ".env");
  if (!fs.existsSync(envPath)) {
    return {};
  }

  return fs.readFileSync(envPath, "utf8").split(/\r?\n/).reduce((values, line) => {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) {
      return values;
    }

    const [key, ...rest] = trimmed.split("=");
    values[key.trim()] = rest.join("=").trim().replace(/^['"]|['"]$/g, "");
    return values;
  }, {});
}

const envFile = loadDotEnv();
const SERVER_PORT = process.env.SERVER_PORT || envFile.SERVER_PORT || "8000";
const API_BASE_URL =
  process.env.API_BASE_URL || envFile.API_BASE_URL || `http://0.0.0.0:${SERVER_PORT}`;

function createWindow() {
  const win = new BrowserWindow({
    width: 860,
    height: 640,
    minWidth: 720,
    minHeight: 520,
    backgroundColor: "#f7f7f4",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  win.loadFile("index.html");
}

async function postJson(pathname, payload) {
  const response = await fetch(`${API_BASE_URL}${pathname}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json; charset=utf-8",
    },
    body: JSON.stringify(payload),
  });

  const result = await response.json();

  if (!response.ok && !Object.prototype.hasOwnProperty.call(result, "success")) {
    return {
      success: false,
      data: null,
      error: `Backend request failed: ${response.status}`,
    };
  }

  return result;
}

ipcMain.handle("analysis:mock-screenshot", async () => {
  try {
    let ocrResult = await postJson("/ocr/image", {});
    if (!ocrResult.success) {
      ocrResult = await postJson("/ocr/mock", { image_id: "test" });
    }

    if (!ocrResult.success) {
      return ocrResult;
    }

    if (ocrResult.data && ocrResult.data.needs_confirm) {
      const lowConfidenceFields = ocrResult.data.low_confidence_fields || [];
      return {
        success: false,
        data: null,
        error: `OCR confidence too low: ${lowConfidenceFields.join(", ")}`,
      };
    }

    return postJson("/analyze", ocrResult.data);
  } catch (error) {
    return {
      success: false,
      data: null,
      error: error.message,
    };
  }
});

ipcMain.handle("feedback:submit", async (event, payload) => {
  try {
    return postJson("/feedback", payload);
  } catch (error) {
    return {
      success: false,
      data: null,
      error: error.message,
    };
  }
});

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
