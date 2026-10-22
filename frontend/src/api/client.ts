import type {
  ApiErrorEnvelope,
  BookingView,
  BookingsEnvelope,
  ChatRequest,
  ChatResponse,
} from "./types";

export const API_PATHS = {
  chat: "./api/chat",
  bookings: "./api/bookings",
  login: "./login",
  logout: "./logout",
} as const;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;
  readonly requestId?: string;

  constructor(
    status: number,
    code: string,
    message: string,
    retryable = false,
    requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.retryable = retryable;
    this.requestId = requestId;
  }
}

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export interface ApiClientOptions {
  fetchImpl?: FetchLike;
  onUnauthorized?: () => void;
}

let redirectInFlight = false;

export function redirectToLogin(): void {
  if (typeof window === "undefined" || redirectInFlight) {
    return;
  }
  redirectInFlight = true;
  window.location.assign(API_PATHS.login);
}

async function readError(response: Response): Promise<ApiError> {
  let code = `http_${response.status}`;
  let message = `The request failed (HTTP ${response.status}).`;
  let retryable = response.status >= 500;
  let requestId: string | undefined;

  const text = await response.text().catch(() => "");
  if (text) {
    let body: ApiErrorEnvelope | null = null;
    try {
      body = JSON.parse(text) as ApiErrorEnvelope;
    } catch {
      body = null;
    }
    if (body && typeof body === "object") {
      if (body.error && typeof body.error === "object") {
        if (typeof body.error.code === "string" && body.error.code.length > 0) {
          code = body.error.code;
        }
        if (typeof body.error.message === "string" && body.error.message.length > 0) {
          message = body.error.message;
        }
        if (typeof body.error.retryable === "boolean") {
          retryable = body.error.retryable;
        }
      }
      if (typeof body.request_id === "string") {
        requestId = body.request_id;
      }
    }
  }

  return new ApiError(response.status, code, message, retryable, requestId);
}

export function createApiClient(options: ApiClientOptions = {}) {
  const fetchImpl: FetchLike =
    options.fetchImpl ?? ((input, init) => globalThis.fetch(input, init));
  const onUnauthorized = options.onUnauthorized ?? redirectToLogin;

  async function requestJson<T>(path: string, init: RequestInit): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");

    const response = await fetchImpl(path, {
      credentials: "same-origin",
      ...init,
      headers,
    });

    if (response.status === 401) {
      onUnauthorized();
      throw new ApiError(
        401,
        "unauthorized",
        "Your session has expired. Sign in again.",
        false,
      );
    }

    if (!response.ok) {
      throw await readError(response);
    }

    if (response.status === 204) {
      return undefined as T;
    }

    return (await response.json()) as T;
  }

  return {
    async sendChat(payload: ChatRequest): Promise<ChatResponse> {
      return requestJson<ChatResponse>(API_PATHS.chat, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    },

    async listBookings(): Promise<BookingView[]> {
      const data = await requestJson<BookingView[] | BookingsEnvelope>(
        API_PATHS.bookings,
        { method: "GET" },
      );

      if (Array.isArray(data)) {
        return data;
      }

      if (
        data &&
        typeof data === "object" &&
        Array.isArray((data as BookingsEnvelope).bookings)
      ) {
        return (data as BookingsEnvelope).bookings ?? [];
      }

      throw new ApiError(
        502,
        "invalid_response",
        "The bookings response could not be read.",
        true,
      );
    },

    async logout(): Promise<void> {
      await fetchImpl(API_PATHS.logout, {
        method: "POST",
        credentials: "same-origin",
      }).catch(() => undefined);
    },
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;

export const api = createApiClient();
