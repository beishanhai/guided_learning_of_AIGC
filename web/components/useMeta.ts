"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, endpoints } from "../lib/api";
import type { Meta } from "../lib/types";

interface MetaState {
  meta: Meta | null;
  loading: boolean;
  error: string;
}

/** 读取 GET /meta（无需鉴权）。 */
export function useMeta(): MetaState {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setMeta(await endpoints.meta());
    } catch (err) {
      setError((err as ApiError).message || "无法读取服务元信息");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return { meta, loading, error };
}

/** 判断当前是否处于离线确定性分析模式。 */
export function isOfflineMultimodal(meta: Meta | null): boolean {
  return !!meta && (meta.providers.multimodal === "offline" || !meta.providers.multimodal);
}
