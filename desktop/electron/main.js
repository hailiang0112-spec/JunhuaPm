"use strict";

const { app, BrowserWindow, Menu, dialog, shell } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const path = require("path");

app.setName("JunhuaPm");

const START_TIMEOUT_MS = 5 * 60 * 1000;
let mainWindow = null;
let backend = null;
let logStream = null;
let origin = "";
let quitting = false;

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
}

function resourcesRoot() {
  if (app.isPackaged) return process.resourcesPath;
  return path.resolve(__dirname, "..", "payload");
}

function findPython(binDir) {
  const names = fs.readdirSync(binDir);
  const versioned = names.filter((name) => /^python3\.\d+$/.test(name)).sort();
  const pick = versioned.length ? versioned[versioned.length - 1] : "python3";
  return path.join(binDir, pick);
}

function splashHtml() {
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>君华装修项目管理</title>
<style>
  html,body{margin:0;height:100%;background:#f4f6f9;color:#111827;
    font:15px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB",sans-serif;}
  main{height:100%;display:flex;align-items:center;justify-content:center;}
  section{width:min(440px,88vw);background:#fff;border:1px solid #d5dce6;border-radius:12px;padding:28px 32px;}
  h1{margin:0 0 8px;font-size:20px;font-weight:600;}
  p{margin:0;color:#5b6779;}
  .bar{margin-top:18px;height:4px;border-radius:99px;background:#e3e8ef;overflow:hidden;}
  .bar i{display:block;height:100%;width:40%;background:#1e5fd0;animation:s 1.1s ease-in-out infinite;}
  @keyframes s{0%{transform:translateX(-120%)}100%{transform:translateX(320%)}}
</style></head><body><main><section>
  <h1>君华装修项目管理</h1>
  <p>正在准备本地数据。第一次打开会写入演示项目，大约需要一两分钟。</p>
  <div class="bar"><i></i></div>
</section></main></body></html>`;
}

function logPath() {
  return path.join(app.getPath("userData"), "backend.log");
}

function appendLog(chunk) {
  if (!logStream) return;
  logStream.write(chunk);
}

function tailLog() {
  try {
    const text = fs.readFileSync(logPath(), "utf8");
    const lines = text.trim().split(/\n/);
    return lines.slice(-30).join("\n");
  } catch {
    return "";
  }
}

function fail(title, detail) {
  const log = logPath();
  dialog.showErrorBox(title, `${detail}\n\n日志：${log}`);
  app.quit();
}

function stopBackend() {
  if (!backend || backend.killed) return;
  try {
    backend.kill("SIGTERM");
  } catch { /* already gone */ }
}

function openApp(port) {
  origin = `http://127.0.0.1:${port}`;
  const win = mainWindow;
  if (!win) return;
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith(origin)) return { action: "allow" };
    shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (event, url) => {
    if (url.startsWith(origin) || url.startsWith("data:")) return;
    event.preventDefault();
    shell.openExternal(url);
  });
  win.loadURL(origin + "/");
}

function waitForHttp(port) {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const probe = () => {
      const req = http.get(`http://127.0.0.1:${port}/api/auth/csrf`, (res) => {
        res.resume();
        if (res.statusCode && res.statusCode < 500) resolve();
        else retry();
      });
      req.on("error", retry);
      req.setTimeout(2000, () => {
        req.destroy();
        retry();
      });
    };
    const retry = () => {
      if (Date.now() - started > 30000) reject(new Error("页面服务没有在预期时间内响应"));
      else setTimeout(probe, 200);
    };
    probe();
  });
}

function startBackend() {
  const root = resourcesRoot();
  const binDir = path.join(root, "runtime", "bin");
  const backendDir = path.join(root, "backend");
  const frontend = path.join(root, "frontend");
  if (!fs.existsSync(binDir) || !fs.existsSync(path.join(frontend, "index.html"))) {
    fail("无法启动", "安装包里缺少运行时或前端页面。请重新下载完整的 JunhuaPm-mac-arm64.zip。");
    return;
  }
  const userData = app.getPath("userData");
  fs.mkdirSync(userData, { recursive: true });
  logStream = fs.createWriteStream(logPath(), { flags: "a" });
  appendLog(`\n---- ${new Date().toISOString()} ----\n`);

  const python = findPython(binDir);
  backend = spawn(python, ["-m", "jh.desktop_serve"], {
    cwd: backendDir,
    env: {
      HOME: process.env.HOME || "",
      USER: process.env.USER || "",
      LOGNAME: process.env.LOGNAME || process.env.USER || "",
      LANG: process.env.LANG || "zh_CN.UTF-8",
      LC_ALL: "zh_CN.UTF-8",
      TMPDIR: process.env.TMPDIR || "/tmp",
      PATH: `${binDir}${path.delimiter}/usr/bin:/bin`,
      JH_DESKTOP: "1",
      JH_DATA_DIR: userData,
      JH_FRONTEND_DIST: frontend,
      JH_SEED: process.env.JH_SEED || "demo",
      DJANGO_SETTINGS_MODULE: "jh.desktop_settings",
      PYTHONUNBUFFERED: "1",
      PYTHONDONTWRITEBYTECODE: "1",
      PYTHONNOUSERSITE: "1",
      PYTHONPATH: backendDir,
    },
  });

  let buffer = "";
  let ready = false;
  const timer = setTimeout(() => {
    if (!ready) fail("启动超时", "本地服务超过 5 分钟还没有就绪。");
  }, START_TIMEOUT_MS);

  const onData = (chunk) => {
    appendLog(chunk);
    buffer += chunk.toString("utf8");
    if (buffer.length > 200000) buffer = buffer.slice(-100000);
    const failed = buffer.match(/JH_FAIL (.*)/);
    if (failed && !ready) {
      clearTimeout(timer);
      fail("启动失败", failed[1]);
      return;
    }
    const match = buffer.match(/JH_READY (\d+)/);
    if (match && !ready) {
      ready = true;
      clearTimeout(timer);
      const port = Number(match[1]);
      waitForHttp(port)
        .then(() => openApp(port))
        .catch((err) => fail("启动失败", err.message));
    }
  };
  backend.stdout.on("data", onData);
  backend.stderr.on("data", onData);
  backend.on("error", (err) => {
    clearTimeout(timer);
    fail("无法启动本地服务", err.message);
  });
  backend.on("exit", (code, signal) => {
    appendLog(`\nbackend exit code=${code} signal=${signal}\n`);
    if (!quitting && !ready) {
      clearTimeout(timer);
      fail("本地服务已退出", tailLog() || `退出码 ${code}`);
    }
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 960,
    minHeight: 640,
    title: "君华装修项目管理",
    backgroundColor: "#f4f6f9",
    show: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(splashHtml()));
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function installMenu() {
  const template = [
    {
      label: "君华装修",
      submenu: [
        { role: "about", label: "关于君华装修项目管理" },
        { type: "separator" },
        { role: "quit", label: "退出" },
      ],
    },
    {
      label: "编辑",
      submenu: [
        { role: "undo", label: "撤销" },
        { role: "redo", label: "重做" },
        { type: "separator" },
        { role: "cut", label: "剪切" },
        { role: "copy", label: "复制" },
        { role: "paste", label: "粘贴" },
        { role: "selectAll", label: "全选" },
      ],
    },
    {
      label: "窗口",
      submenu: [
        { role: "reload", label: "重新加载" },
        { role: "togglefullscreen", label: "进入全屏" },
        { role: "minimize", label: "最小化" },
        { role: "close", label: "关闭窗口" },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

if (gotLock) {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  });

  app.whenReady().then(() => {
    app.setAboutPanelOptions({
      applicationName: "君华装修项目管理",
      applicationVersion: app.getVersion(),
      copyright: "本地数据在“应用程序支持 / JunhuaPm”",
    });
    installMenu();
    createWindow();
    startBackend();
  });

  app.on("before-quit", () => {
    quitting = true;
    stopBackend();
  });

  app.on("window-all-closed", () => {
    app.quit();
  });
}
