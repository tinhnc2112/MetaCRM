import { app, BrowserWindow, ipcMain, shell } from "electron";
import path from "node:path";

const isDevelopment = Boolean(process.env.VITE_DEV_SERVER_URL);
const PROTOCOL = "metacrm";

// requestSingleInstanceLock must be called before app.whenReady so that
// the "second-instance" event fires when a duplicate instance is launched
// (used to handle metacrm:// deep links on Windows / Linux).
if (!app.requestSingleInstanceLock()) {
  app.quit();
}

if (!isDevelopment) {
  // Register as default handler for metacrm:// deep links (packaged app)
  app.setAsDefaultProtocolClient(PROTOCOL);
}

function getMainWindow(): BrowserWindow | null {
  return BrowserWindow.getAllWindows()[0] ?? null;
}

function handleDeepLink(url: string): void {
  const win = getMainWindow();
  if (!win) return;

  try {
    const parsed = new URL(url);
    // metacrm://settings/facebook?facebook=connected
    const routePath = `/${parsed.hostname}${parsed.pathname}`;
    const search = parsed.search;
    const target = `${routePath}${search}`;

    if (win.isMinimized()) win.restore();
    win.focus();
    // Forward the deep-link path into the renderer via IPC
    win.webContents.send("deep-link", target);
  } catch {
    // Malformed URL — ignore
  }
}

function createMainWindow(): BrowserWindow {
  const mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 1024,
    minHeight: 680,
    title: "MetaCRM",
    backgroundColor: "#f5f7fb",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  if (isDevelopment && process.env.VITE_DEV_SERVER_URL) {
    void mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL);
    mainWindow.webContents.openDevTools({ mode: "detach" });
  } else {
    void mainWindow.loadFile(path.join(__dirname, "../dist/index.html"));
  }

  return mainWindow;
}

ipcMain.handle("app:get-version", () => app.getVersion());

app.whenReady().then(() => {
  createMainWindow();

  // macOS: deep link arrives via "open-url" event
  app.on("open-url", (_event, url) => {
    handleDeepLink(url);
  });

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow();
    }
  });
});

// Windows / Linux: deep link arrives as a second-instance argv
app.on("second-instance", (_event, argv) => {
  const url = argv.find((arg) => arg.startsWith(`${PROTOCOL}://`));
  if (url) handleDeepLink(url);
  const win = getMainWindow();
  if (win) {
    if (win.isMinimized()) win.restore();
    win.focus();
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
