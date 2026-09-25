"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { clearSession, getStoredUser, getToken } from "../lib/api";
import type { User } from "../lib/types";

const LINKS = [
  { href: "/projects", label: "项目" },
  { href: "/", label: "登录" },
];

export default function TopNav() {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setUser(getToken() ? getStoredUser() : null);
    setReady(true);
  }, [pathname]);

  function logout() {
    clearSession();
    setUser(null);
    router.push("/");
  }

  return (
    <header className="topbar">
      <Link href="/" className="brand">
        拆镜学
        <small>学习闭环</small>
      </Link>
      <nav className="row" style={{ gap: 4 }}>
        {LINKS.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className={
              "navlink" +
              (link.href === "/projects" && pathname.startsWith("/projects") ? " navlink-active" : "")
            }
          >
            {link.label}
          </Link>
        ))}
      </nav>
      <div className="spacer" />
      {ready && user ? (
        <div className="row" style={{ gap: 8 }}>
          <span className="dim">
            {user.display_name || user.subject} · {user.role}
          </span>
          <button type="button" className="btn-ghost btn-sm" onClick={logout}>
            退出
          </button>
        </div>
      ) : (
        ready && <span className="dim">未登录</span>
      )}
    </header>
  );
}
