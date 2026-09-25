/**
 * 拆镜学 API 类型定义。
 *
 * 形状来源：
 * - docs/openapi.json（35 个端点）
 * - backend/app/schemas.py / serializers.py（OpenAPI 中 additionalProperties=true 的部分按实现补充）
 */

/* ---------------- 通用 ---------------- */

/** 统一错误体（§5.3）。 */
export interface ApiErrorBody {
  code: string;
  message: string;
  request_id: string;
  details?: unknown;
}

/* ---------------- 鉴权 ---------------- */

export interface User {
  id: string;
  subject: string;
  display_name: string;
  role: string;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

/* ---------------- 元信息 ---------------- */

export interface IntentOption {
  key: string;
  label: string;
  goal: string;
  practice_emphasis: string;
}

export interface TaskLevelMeta {
  key: string;
  label: string;
  fixed_constraint: string;
  learner_change: string;
  evaluation_focus: string;
}

export interface MetaProviders {
  multimodal: string;
  multimodal_model_id: string;
  asr: string;
  storage: string;
  queue: string;
}

export interface MetaLimits {
  max_upload_bytes: number;
  min_duration_ms: number;
  max_duration_ms: number;
  max_height: number;
  signed_url_ttl_seconds: number;
  max_frames_per_asset: number;
}

export interface Meta {
  intents: IntentOption[];
  task_levels: TaskLevelMeta[];
  versions: Record<string, string>;
  knowledge_card_count: number;
  providers: MetaProviders;
  limits: MetaLimits;
  disclosure: string;
}

/* ---------------- 项目与素材 ---------------- */

export interface Project {
  id: string;
  title: string;
  description: string;
  rights_note: string;
  created_at: string;
  deleted_at: string | null;
  asset_count: number;
  analysis_count: number;
}

export type AssetStatus = "pending" | "uploaded" | "ready" | "rejected" | "deleted";

export interface Asset {
  id: string;
  project_id: string;
  status: AssetStatus | string;
  duration_ms: number;
  width: number;
  height: number;
  fps: number;
  has_audio: boolean;
  video_codec: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
  is_vfr: boolean;
  rejection_code: string;
  rejection_reason: string;
  /** 服务端返回的短期播放地址；本地存储时是相对路径，需要补 origin。 */
  playback_url: string;
  created_at: string;
}

export interface UploadTicket {
  asset_id: string;
  project_id: string;
  object_key: string;
  upload_url: string;
  upload_method: string;
  expires_in: number;
  max_bytes: number;
  note: string;
}

export interface MediaCheck {
  check: string;
  passed: boolean;
  value?: unknown;
}

export interface MediaValidation {
  asset: Asset;
  validated: boolean;
  checks: MediaCheck[];
}

/* ---------------- 任务（Job） ---------------- */

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled" | string;

export interface JobStage {
  stage: string;
  status: string;
  attempt: number;
  duration_ms: number;
  provider_request_id: string;
  version: string;
  input_summary: Record<string, unknown>;
  output_summary: Record<string, unknown>;
  error: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Job {
  id: string;
  type: string;
  status: JobStatus;
  stage: string;
  attempt: number;
  max_attempts: number;
  progress: number;
  partial: boolean;
  error_code: string;
  error_message: string;
  result_type: string;
  result_id: string;
  estimated_cost_cny: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  stages: JobStage[];
  links: Record<string, string>;
}

export interface JobCreated {
  job_id: string;
  status: string;
  stage: string;
  idempotent_replay: boolean;
}

/* ---------------- 分析 ---------------- */

export interface KnowledgeCard {
  id: string;
  title: string;
  topic?: string;
  content: string;
  source: string;
}

export interface ShotEvidence {
  timestamp_ms: number;
  frame_id: string;
  frame_key: string;
}

export interface ShotFrame {
  frame_key: string;
  url: string;
}

export interface Shot {
  id: string;
  shot_ref: string;
  index: number;
  start_ms: number;
  end_ms: number;
  duration_ms: number;
  observation: string;
  shot_scale: string;
  camera_motion: string;
  interpretation: string;
  alternative: string;
  narrative_function: string;
  dialogue: string;
  frames: ShotFrame[];
  frame_keys: string[];
  evidence: ShotEvidence[];
  knowledge_ids: string[];
  knowledge: KnowledgeCard[];
  unknowns: string[];
  confidence: number;
  review_status: string;
  source: string;
}

export interface AnalysisCoverage {
  shot_count?: number;
  frame_count?: number;
  frames_truncated?: boolean;
  notes?: string[];
  warnings?: string[];
  partial?: boolean;
  provider?: string;
  asr_provider?: string;
  asr_note?: string;
  human_edited?: boolean;
  supersedes?: string;
  [key: string]: unknown;
}

export interface AnalysisTranscriptSegment {
  start_ms: number;
  end_ms: number;
  text: string;
}

export interface AnalysisTranscript {
  language?: string;
  provider?: string;
  note?: string;
  segments?: AnalysisTranscriptSegment[];
  [key: string]: unknown;
}

export interface AnalysisMedia {
  width?: number;
  height?: number;
  fps?: number;
  is_vfr?: boolean;
  duration_ms?: number;
  container?: string;
  video_codec?: string;
  has_audio?: boolean;
  [key: string]: unknown;
}

/** 与 backend/app/learning/metrics.py::compute_metrics 一致。 */
export interface AnalysisMetrics {
  shot_count?: number;
  duration_ms?: number;
  shot_duration_list?: number[];
  shot_duration_mean_ms?: number;
  shot_duration_median_ms?: number;
  shot_duration_min_ms?: number;
  shot_duration_max_ms?: number;
  cut_rate_per_minute?: number;
  scale_distribution?: Record<string, number>;
  scale_unknown_count?: number;
  scale_known_count?: number;
  scale_unknown_note?: string;
  motion_distribution?: Record<string, number>;
  narrative_function_distribution?: Record<string, number>;
  has_dialogue_shots?: number;
  [key: string]: unknown;
}

export interface Analysis {
  id: string;
  asset_id: string;
  project_id: string;
  version: number;
  kind: string;
  intent: string;
  status: string;
  model_id: string;
  prompt_version: string;
  knowledge_version: string;
  schema_version: string;
  pipeline_version: string;
  coverage: AnalysisCoverage;
  transcript: AnalysisTranscript;
  media: AnalysisMedia;
  metrics: AnalysisMetrics;
  unknowns: { items?: string[]; policy?: string };
  review_status: string;
  edited_by_user: boolean;
  is_demo_prebuilt: boolean;
  created_at: string;
  shots: Shot[];
}

export interface AnalysisSummary {
  id: string;
  project_id: string;
  asset_id: string;
  version: number;
  kind: string;
  intent: string;
  status: string;
  shot_count: number;
  created_at: string;
}

export interface ShotExplanation {
  shot_ref: string;
  intent: string;
  observation: string;
  fact_lines: string[];
  intent_reading: string;
  interpretation: string;
  alternative: string;
  evidence: ShotEvidence[];
  knowledge_ids: string[];
  unknowns: string[];
}

export interface ExplanationsResponse {
  analysis_id: string;
  intent: string;
  intent_label: string;
  fact_timeline_unchanged: boolean;
  note: string;
  explanations: ShotExplanation[];
}

export interface ShotPatch {
  shot_ref: string;
  start_ms?: number | null;
  end_ms?: number | null;
  shot_scale?: string | null;
  camera_motion?: string | null;
  narrative_function?: string | null;
  observation?: string | null;
  interpretation?: string | null;
  review_status?: "unreviewed" | "confirmed" | "rejected" | null;
}

export interface ShotsPatchRequest {
  expected_version: number;
  review_status?: "unreviewed" | "confirmed" | "rejected";
  shots: ShotPatch[];
}

export interface AnalysisVersionEntry {
  id: string;
  version: number;
  status: string;
  edited_by_user: boolean;
  supersedes_id: string | null;
  created_at: string;
  learning_task_ids: string[];
}

export interface AnalysisVersionsResponse {
  analysis_id: string;
  versions: AnalysisVersionEntry[];
}

/* ---------------- 学习任务 ---------------- */

export type TaskLevel = "imitate" | "variant" | "original";

export interface TaskPrerequisite {
  knowledge_id: string;
  title: string;
  content: string;
  source: string;
  reviewer?: string;
}

export interface TaskStep {
  index: number;
  title: string;
  detail: string;
}

export interface TaskRubricItem {
  key: string;
  criterion: string;
  max_score: number;
  scale: string;
}

export interface LearningTask {
  id: string;
  analysis_id: string;
  intent: string;
  level: TaskLevel | string;
  title: string;
  objective: string;
  prerequisites: TaskPrerequisite[];
  steps: TaskStep[];
  constraints: Record<string, unknown>;
  submission_requirements: string[];
  rubric: TaskRubricItem[];
  estimated_minutes: number;
  tools: string[];
  reference_metrics: AnalysisMetrics;
  version: number;
  knowledge_version?: string;
  created_at: string;
}

/* ---------------- 作业与反馈 ---------------- */

export interface Submission {
  id: string;
  task_id: string;
  asset_id: string;
  analysis_id: string;
  submission_analysis_id: string;
  learner_reason: string;
  storyboard_text: string;
  status: string;
  version: number;
  created_at: string;
}

export interface MetricDelta {
  reference: number;
  submission: number;
  delta: number | null;
}

export interface DistributionDiff {
  reference: Record<string, number>;
  submission: Record<string, number>;
}

export interface FeedbackMetrics {
  shot_count?: MetricDelta;
  shot_duration_mean_ms?: MetricDelta;
  shot_duration_max_ms?: MetricDelta;
  cut_rate_per_minute?: MetricDelta;
  duration_ms?: MetricDelta;
  scale_distribution?: DistributionDiff;
  motion_distribution?: DistributionDiff;
  [key: string]: unknown;
}

export type AlignmentCertainty = "confirmed" | "candidate" | "unmatched";

export interface Alignment {
  reference_shot_ref: string;
  submission_shot_ref: string;
  method: string;
  certainty: AlignmentCertainty | string;
  reference_time_ms: number | null;
  submission_time_ms: number | null;
  reference_duration_ms?: number;
  submission_duration_ms?: number;
  duration_delta_ms?: number;
  relative_time_delta?: number;
  reference_summary?: string;
  submission_summary?: string;
  note: string;
}

export interface Suggestion {
  id: string;
  priority: number;
  target: string;
  action: string;
  goal_link: string;
}

export interface FeedbackEvidenceItem {
  shot_ref: string;
  start_ms: number;
  end_ms: number;
  frames: string[];
  observation: string;
  knowledge_ids: string[];
  unknowns: string[];
}

export interface StoryboardCheck {
  key: string;
  passed: boolean;
  detail: string;
}

export interface StoryboardMetrics {
  mode?: string;
  note?: string;
  shot_lines?: number;
  scales_found?: string[];
  checks?: StoryboardCheck[];
  passed_count?: number;
  total_count?: number;
  total_duration_ms?: number;
  per_criterion?: Record<string, boolean>;
  [key: string]: unknown;
}

export interface ConstraintResult {
  constraint: string;
  passed: boolean;
  detail: string;
}

export interface Feedback {
  id: string;
  submission_id: string;
  summary: string;
  metrics: FeedbackMetrics;
  alignments: Alignment[];
  suggestions: Suggestion[];
  evidence: { reference?: FeedbackEvidenceItem[]; submission?: FeedbackEvidenceItem[] };
  storyboard_metrics: StoryboardMetrics;
  review_status: string;
  created_at: string;
}
