/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 受限沙箱下 Node 无法用管道 stdio 派生子进程（spawn EPERM），
  // 因此让构建使用 worker_threads 而不是 child_process。
  experimental: {
    workerThreads: true,
    cpus: 1,
    webpackBuildWorker: false,
  },
};

export default nextConfig;
