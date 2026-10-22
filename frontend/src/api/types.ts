export const PATIENT_ID = "P001";

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

export interface ChatResponse {
  conversation_id: string;
  message_id: string;
  assistant_message: string;
  sources?: SourceRef[];
  booking_draft?: BookingDraftView | null;
  events?: ChatEvent[];
}

export interface ChatRequest {
  conversation_id: string | null;
  message_id: string;
  message: string;
  patient_id: string;
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
