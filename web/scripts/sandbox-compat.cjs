/**
 * 受限沙箱下的 Next.js 兼容层（仅构建/启动期使用，不进入任何业务代码）。
 *
 * 本机 DSH 文件沙箱禁止进程通过命名管道建立 stdio / IPC，所以两处 Next 默认行为会失败：
 *
 * 1) 构建：Next 默认用 child_process 派生构建 worker（jest-worker），直接 spawn EPERM。
 *    处理：next.config.mjs 打开 experimental.workerThreads，改用 worker_threads；
 *    但 Next 15 会把 nextConfig.generateBuildId（默认 ()=>null）、nextConfig.exportPathMap
 *    等函数一起 postMessage 给静态生成 worker，抛 DataCloneError。
 *    这里包裹 Worker.prototype.postMessage，只在结构化克隆失败时把不可克隆成员
 *    （函数 / symbol）降级为可克隆数据（保留共享引用与循环引用）。worker 侧只读纯数据。
 *
 * 2) 开发服务器：next dev 会 child_process.fork 出 start-server 子进程并通过 IPC 通信，
 *    fork 的 IPC 通道在 Windows 上就是命名管道，同样 EPERM。
 *    这里拦截指向 server/lib/start-server 的 fork，改为在**当前进程内**启动服务器，
 *    并用一个事件对象模拟子进程的 message/send 握手（nextWorkerReady → nextWorkerOptions
 *    → nextServerReady）。对 Next 的调用方而言协议完全一致。
 *
 * 调试：设置 CJ_SANDBOX_COMPAT_DEBUG=1 打印被降级的成员。
 */
const path = require("node:path");
const { EventEmitter } = require("node:events");
const childProcess = require("node:child_process");

const debug = process.env.CJ_SANDBOX_COMPAT_DEBUG === "1";

/* ------------------------------------------------------------------ *
 * 1) worker_threads：postMessage 不可克隆成员降级
 * ------------------------------------------------------------------ */

const { Worker } = require("node:worker_threads");

function isPassThrough(value) {
  if (value === null || typeof value !== "object") return true;
  if (value instanceof ArrayBuffer || ArrayBuffer.isView(value)) return true;
  if (typeof SharedArrayBuffer !== "undefined" && value instanceof SharedArrayBuffer) return true;
  return false;
}

function sanitize(value, memo) {
  if (typeof value === "function" || typeof value === "symbol") return undefined;
  if (isPassThrough(value)) return value;
  if (memo.has(value)) return memo.get(value);

  if (Array.isArray(value)) {
    const out = [];
    memo.set(value, out);
    for (const item of value) out.push(sanitize(item, memo));
    return out;
  }
  if (value instanceof Map) {
    const out = new Map();
    memo.set(value, out);
    value.forEach((item, key) => out.set(key, sanitize(item, memo)));
    return out;
  }
  if (value instanceof Set) {
    const out = new Set();
    memo.set(value, out);
    value.forEach((item) => {
      const clean = sanitize(item, memo);
      if (clean !== undefined) out.add(clean);
    });
    return out;
  }
  const out = {};
  memo.set(value, out);
  for (const key of Object.keys(value)) {
    const item = sanitize(value[key], memo);
    if (item !== undefined) out[key] = item;
  }
  return out;
}

function collectFunctions(value, at, found, seen) {
  if (typeof value === "function") {
    found.push(at + " (源码: " + String(value).slice(0, 60) + ")");
    return;
  }
  if (value === null || typeof value !== "object") return;
  if (seen.has(value)) return;
  seen.add(value);
  if (Array.isArray(value)) {
    value.forEach((item, index) => collectFunctions(item, at + "[" + index + "]", found, seen));
    return;
  }
  for (const key of Object.keys(value)) collectFunctions(value[key], at + "." + key, found, seen);
}

function canClone(value) {
  try {
    structuredClone(value);
    return true;
  } catch {
    return false;
  }
}

const originalPostMessage = Worker.prototype.postMessage;
Worker.prototype.postMessage = function patchedPostMessage(value, transferList) {
  let payload = value;
  if (!canClone(value)) {
    if (debug) {
      const found = [];
      try {
        collectFunctions(value, "payload", found, new WeakSet());
      } catch {
        /* 诊断失败不影响运行 */
      }
      console.error("[sandbox-compat] 不可克隆的成员：\n  " + found.join("\n  "));
    }
    payload = sanitize(value, new Map());
  }
  return originalPostMessage.call(this, payload, transferList);
};

/* ------------------------------------------------------------------ *
 * 2) child_process.fork：start-server 改为进程内启动
 * ------------------------------------------------------------------ */

const originalFork = childProcess.fork;

function isStartServerFork(modulePath) {
  return typeof modulePath === "string" && modulePath.split(path.sep).join("/").includes("server/lib/start-server");
}

function createInProcessChild(modulePath) {
  const child = new EventEmitter();
  child.pid = process.pid;
  child.connected = true;
  child.disconnect = () => {
    child.connected = false;
  };
  child.kill = () => {
    child.connected = false;
    setImmediate(() => child.emit("exit", 0, null));
    return true;
  };

  child.send = (message) => {
    if (message && typeof message === "object" && message.nextWorkerOptions) {
      if (debug) console.error("[sandbox-compat] 在当前进程内启动 Next dev server");
      // eslint-disable-next-line global-require
      const { startServer } = require(modulePath);
      Promise.resolve()
        .then(() => startServer(message.nextWorkerOptions))
        .then(() => {
          child.emit("message", { nextServerReady: true, port: process.env.PORT });
        })
        .catch((error) => {
          console.error(error);
          process.exit(1);
        });
    }
    return true;
  };

  // 模拟子进程启动完成后的第一条握手消息
  setImmediate(() => {
    if (child.connected) child.emit("message", { nextWorkerReady: true });
  });
  return child;
}

childProcess.fork = function patchedFork(modulePath) {
  if (isStartServerFork(modulePath)) {
    return createInProcessChild(modulePath);
  }
  return originalFork.apply(this, arguments);
};
