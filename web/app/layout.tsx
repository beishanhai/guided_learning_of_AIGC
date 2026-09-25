import type { Metadata } from "next";
import "./globals.css";
import TopNav from "../components/TopNav";

// 全部页面都依赖浏览器会话（localStorage 中的 Bearer），不做静态预渲染。
// 同时避免静态生成 worker 在受限沙箱下的 worker_threads 序列化问题。
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "拆镜学 · 学习闭环",
  description: "上传参考片 → 拆解镜头 → 生成学习任务 → 提交作业 → 证据化反馈",
};

// 本项目以 AGPL-3.0 发布：通过网络与之交互的用户必须能拿到对应源码（AGPL 第 13 条）。
// 部署时请把 NEXT_PUBLIC_SOURCE_URL 指向你实际部署版本的仓库地址。
const SOURCE_URL =
  process.env.NEXT_PUBLIC_SOURCE_URL || "https://github.com/your-org/chai-jing-xue";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <TopNav />
        <main>{children}</main>
        <footer className="site-footer">
          <span>拆镜学 · 学习闭环原型</span>
          <span className="site-footer-sep">|</span>
          <span>
            许可：AGPL-3.0（不提供担保，分析结果不构成版权判定）
          </span>
          <span className="site-footer-sep">|</span>
          <a href={SOURCE_URL} target="_blank" rel="noopener noreferrer">
            获取源代码
          </a>
        </footer>
      </body>
    </html>
  );
}
