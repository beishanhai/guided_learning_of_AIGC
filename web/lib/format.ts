/** 展示层格式化与枚举标签（与 backend/app/pipeline/schema.py 保持一致）。 */

export const SHOT_SCALE_LABELS: Record<string, string> = {
  extreme_wide: "大远景",
  wide: "全景",
  medium: "中景",
  medium_close: "中近景",
  close_up: "近景",
  extreme_close_up: "特写",
  unknown: "未知",
};

export const CAMERA_MOTION_LABELS: Record<string, string> = {
  static: "固定",
  pan: "横摇",
  tilt: "纵摇",
  dolly: "移动",
  zoom: "变焦",
  handheld: "手持",
  unknown: "未知",
};

export const NARRATIVE_FUNCTION_LABELS: Record<string, string> = {
  establish: "建立环境",
  introduce_subject: "引入主体",
  develop: "推进信息",
  emphasize_emotion: "情绪强调",
  transition: "转场过渡",
  unknown: "未判定",
};

export const INTENT_LABELS: Record<string, string> = {
  shot_language: "镜头语言",
  narrative_rhythm: "叙事节奏",
};

export const LEVEL_LABELS: Record<string, string> = {
  imitate: "模仿",
  variant: "变体",
  original: "原创",
};

export const ASSET_STATUS_LABELS: Record<string, string> = {
  pending: "待上传",
  uploaded: "已上传待校验",
  ready: "可用",
  rejected: "未通过校验",
  deleted: "已删除",
};

export const JOB_STATUS_LABELS: Record<string, string> = {
  queued: "排队中",
  running: "处理中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

export const CONSTRAINT_LABELS: Record<string, string> = {
  keep_shot_count: "保持镜头数量",
  duration_range_ms: "成片时长范围",
  shot_count_range: "镜头数量范围",
  min_distinct_scales: "最少可判定景别种类",
  max_mean_duration_ms: "平均镜头时长上限",
  min_mean_duration_ms: "平均镜头时长下限",
  single_shot_max_ms: "单镜头时长上限",
  must_state_objective: "必须写清表达目标",
  must_explain_change: "必须说明修改理由",
  keep_narrative_function: "保持主要叙事功能",
  may_change_subject: "可以更换主体",
  level_note: "级别固定约束",
};

/** 景别/运镜/功能的中文标签；unknown 一律显示「未知」，不做猜测。 */
export function scaleLabel(value?: string | null): string {
  const key = value || "unknown";
  return SHOT_SCALE_LABELS[key] || "未知";
}

export function motionLabel(value?: string | null): string {
  const key = value || "unknown";
  return CAMERA_MOTION_LABELS[key] || "未知";
}

export function functionLabel(value?: string | null): string {
  const key = value || "unknown";
  return NARRATIVE_FUNCTION_LABELS[key] || "未判定";
}

export function intentLabel(value?: string | null): string {
  return INTENT_LABELS[value || ""] || value || "未指定";
}

export function levelLabel(value?: string | null): string {
  return LEVEL_LABELS[value || ""] || value || "未指定";
}

export function isUnknown(value?: string | null): boolean {
  return !value || value === "unknown";
}

/** 毫秒 -> "1:23.4"。 */
export function formatDuration(ms?: number | null): string {
  if (ms === undefined || ms === null || Number.isNaN(ms)) return "—";
  const total = Math.max(0, ms) / 1000;
  const minutes = Math.floor(total / 60);
  const seconds = total - minutes * 60;
  return minutes + ":" + (seconds < 10 ? "0" : "") + seconds.toFixed(1);
}

/** 毫秒 -> "1.23 秒"。 */
export function formatSeconds(ms?: number | null, digits = 2): string {
  if (ms === undefined || ms === null || Number.isNaN(ms)) return "—";
  return (ms / 1000).toFixed(digits) + " 秒";
}

export function formatMs(ms?: number | null): string {
  if (ms === undefined || ms === null || Number.isNaN(ms)) return "—";
  return Math.round(ms) + " ms";
}

export function formatBytes(bytes?: number | null): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return (index === 0 ? value.toFixed(0) : value.toFixed(1)) + " " + units[index];
}

export function formatDateTime(iso?: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    date.getFullYear() +
    "-" +
    pad(date.getMonth() + 1) +
    "-" +
    pad(date.getDate()) +
    " " +
    pad(date.getHours()) +
    ":" +
    pad(date.getMinutes())
  );
}

/** 把约束对象渲染成中文字段行。 */
export function describeConstraint(key: string, value: unknown): string {
  const label = CONSTRAINT_LABELS[key] || key;
  if (value === null || value === undefined) return label + "：—";
  if (typeof value === "boolean") return label + "：" + (value ? "是" : "否");
  if (Array.isArray(value)) {
    if (key === "duration_range_ms" || key === "shot_count_range") {
      const numbers = value.map((item) => Number(item));
      if (key === "duration_range_ms") {
        return label + "：" + formatSeconds(numbers[0], 1) + " — " + formatSeconds(numbers[1], 1);
      }
      return label + "：" + numbers[0] + " — " + numbers[1] + " 个";
    }
    return label + "：" + value.map((item) => String(item)).join("、");
  }
  if (typeof value === "number") {
    if (key.endsWith("_ms")) return label + "：" + formatSeconds(value, 1);
    return label + "：" + String(value);
  }
  return label + "：" + String(value);
}

/** 依据镜头时长/相对位置计算时间线色块颜色。 */
export function shotTone(index: number): string {
  const palette = ["#4f8cff", "#22b8a6", "#f2a13b", "#c76bff", "#ff6b81", "#5ad1ff", "#9ad35a"];
  return palette[index % palette.length];
}
