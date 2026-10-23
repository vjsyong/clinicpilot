export const PATIENT_ID = "P001";

export type ModelProvider = "local" | "deepseek";

export interface SourceRef {
  source_file: string;
  record_id: string;
}

export interface BookingDraftView {
  draft_id: string;
  version: number;
  status: string;
  doctor_id?: string | null;
  doctor_name?: string | null;
  treatment_id?: string | null;
  treatment_name?: string | null;
  clinic_id?: string | null;
  clinic_name?: string | null;
  local_date?: string | null;
  local_time?: string | null;
  timezone?: string | null;
  starts_at_utc?: string | null;
  notes?: string | null;
  missing_fields?: string[];
  booking_id?: string | null;
  editing_booking_id?: string | null;
  confirmation_message_id?: string | null;
  confirmation_version?: number | null;
}

export interface BookingView {
  booking_id: string;
  patient_id: string;
  doctor_id: string;
  doctor_name: string;
  treatment_id: string;
  treatment_name: string;
  clinic_id: string;
  clinic_name: string;
  local_date: string;
  local_time: string;
  timezone: string;
  starts_at_utc: string;
  status: string;
  notes?: string | null;
}

export interface ChatEvent {
  type: string;
  booking?: BookingView | null;
}

export interface SlotSuggestion {
  local_date: string;
  local_time: string;
  timezone: string;
  label: string;
}

export interface NextStep {
  kind:
    | "collect_details"
    | "choose_slot"
    | "confirm_booking"
    | "confirm_action"
    | "completed";
  missing_fields: string[];
  suggestions: SlotSuggestion[];
  draft_version?: number | null;
  action_id?: string | null;
  booking_id?: string | null;
  action_booking?: BookingView | null;
  action_bookings?: BookingView[] | null;
  message?: string | null;
}

export interface ChatResponse {
  conversation_id: string;
  message_id: string;
  assistant_message: string;
  sources?: SourceRef[];
  booking_draft?: BookingDraftView | null;
  events?: ChatEvent[];
  next_step?: NextStep | null;
}

export interface ChatRequest {
  conversation_id: string | null;
  message_id: string;
  message: string;
  patient_id: string;
  model: ModelProvider;
}

export interface ModelInfo {
  id: ModelProvider;
  label: string;
  model: string;
  available: boolean;
  hint?: string | null;
}

export interface ModelsResponse {
  default: ModelProvider;
  models: ModelInfo[];
  verified?: boolean;
}

export interface ApiErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
    retryable?: boolean;
  };
  request_id?: string;
}

export interface BookingsEnvelope {
  bookings?: BookingView[];
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  turn_count: number;
  active_turn_id?: string | null;
}

export interface ToolTrace {
  id?: string | null;
  name: string;
  args: Record<string, unknown>;
  ok: boolean;
  summary: string;
  sources: SourceRef[];
  running?: boolean;
}

export interface TranscriptTurn {
  turn_id: string;
  client_message_id: string;
  user: string;
  status: string;
  created_at: string;
  assistant?: string | null;
  sources: SourceRef[];
  booking_draft?: BookingDraftView | null;
  tools: ToolTrace[];
  events: ChatEvent[];
  next_step?: NextStep | null;
}

export interface ConversationTranscript {
  conversation: ConversationSummary;
  turns: TranscriptTurn[];
  draft?: BookingDraftView | null;
}

export interface KnowledgeRecord {
  document_id: string;
  source_file: string;
  record_id: string;
  citation: string;
  text: string;
  metadata: Record<string, string>;
}

export interface KnowledgeStatus {
  ready: boolean;
  records: number;
  model: string;
  revision: string;
}

export interface ChatStreamSession {
  conversation_id: string;
  turn_id: string;
  message_id: string;
}

export interface ChatStreamError {
  code: string;
  message: string;
  retryable: boolean;
}

export type ChatStreamEvent =
  | { event: "session"; data: ChatStreamSession }
  | { event: "status"; data: { stage: string } }
  | { event: "content"; data: { delta: string } }
  | { event: "content_break"; data: Record<string, never> }
  | { event: "tool_start"; data: { id: string; name: string; args: Record<string, unknown> } }
  | {
      event: "tool_end";
      data: {
        id: string;
        name: string;
        ok: boolean;
        summary: string;
        sources?: SourceRef[];
      };
    }
  | { event: "sources"; data: { sources: SourceRef[] } }
  | { event: "draft"; data: { draft: BookingDraftView } }
  | { event: "next_step"; data: { next_step: NextStep } }
  | { event: "done"; data: ChatResponse }
  | { event: "error"; data: ChatStreamError }
  | { event: "stopped"; data: Record<string, never> };

export interface ResetResult {
  restored_bookings: string[];
  removed_bookings: number;
  cleared_conversations: number;
}

export interface AuditEvent {
  id: string;
  conversation_id: string | null;
  turn_id: string | null;
  event_type: string;
  name: string;
  status: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface AuditPricing {
  input_per_million_usd: number;
  output_per_million_usd: number;
  cached_input_per_million_usd: number;
  version: string;
}

export interface AuditEnvelope {
  events: AuditEvent[];
  pricing: AuditPricing;
}
