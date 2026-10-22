import { expect, test, type APIResponse, type Page, type Route } from '@playwright/test';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import * as path from 'node:path';

/**
 * Browser acceptance tests for the packaged ClinicPilot container.
 *
 * The suite assumes the real application, real SQLite database and the
 * deterministic generation stub from compose.ci.yaml are already running on
 * 127.0.0.1:8000 under the synthetic CI prefix. It never calls a live model.
 *
 * The persistence test deliberately runs in a second Playwright invocation,
 * after CI has restarted the app container. The first invocation writes the
 * created booking to E2E_STATE_FILE so the second invocation can prove the row
 * survived a process restart.
 */

const PREFIX = process.env.CLINICPILOT_E2E_PREFIX ?? '/ci-clinicpilot-0123456789/';
const PASSWORD = process.env.CLINICPILOT_E2E_PASSWORD ?? 'clinicpilot-ci-password';
const STATE_FILE =
  process.env.E2E_STATE_FILE ??
  path.join(tmpdir(), 'clinicpilot-e2e', 'persisted-booking.json');
const EXPECTED_DATE = '2030-06-17';
const EXPECTED_TIME = '15:00';
const EXPECTED_DOCTOR = 'Dr. James Wilson';
const EXPECTED_TREATMENT = 'Joint & Pain Consultation';

type Booking = {
  booking_id: string;
  patient_id: string;
  doctor_id: string;
  doctor_name: string;
  treatment_id: string;
  treatment_name: string;
  local_date: string;
  local_time: string;
  status: string;
};

type ChatResponse = {
  conversation_id: string;
  message_id: string;
  assistant_message: string;
  booking_draft: {
    draft_id: string;
    version: number;
    status: string;
    doctor_id: string | null;
    treatment_id: string | null;
    local_date: string | null;
    local_time: string | null;
  } | null;
  events: Array<{ type: string; booking?: Booking }>;
};

function apiPath(suffix: string): string {
  return `${PREFIX.replace(/\/$/, '')}/${suffix.replace(/^\//, '')}`;
}

function bookingRows(page: Page) {
  return page.locator(
    '[data-testid="booking-row"], [data-testid="bookings-table"] tbody tr, table tbody tr, [role="table"] [role="row"]',
  );
}

function messageBox(page: Page) {
  return page
    .getByTestId('chat-input')
    .or(page.getByRole('textbox', { name: /message|ask|chat|type/i }))
    .or(page.locator('textarea'))
    .first();
}

function sendButton(page: Page) {
  return page
    .getByTestId('chat-send')
    .or(page.getByRole('button', { name: /send|ask|submit/i }))
    .first();
}

async function login(page: Page): Promise<void> {
  await page.goto(PREFIX);
  const password = page.getByTestId('login-password').or(page.getByLabel(/password/i)).first();
  await expect(password).toBeVisible();
  await password.fill(PASSWORD);

  const submit = page
    .getByTestId('login-submit')
    .or(page.getByRole('button', { name: /sign in|log in|login|continue/i }))
    .first();

  const initialBookings = page
    .waitForResponse(
      (response) =>
        response.request().method() === 'GET' &&
        new URL(response.url()).pathname === apiPath('api/bookings') &&
        response.status() === 200,
      { timeout: 15_000 },
    )
    .catch(() => null);

  await Promise.all([
    page.waitForURL((url) => !url.pathname.replace(/\/$/, '').endsWith('/login')),
    submit.click(),
  ]);

  await expect(password).toHaveCount(0);
  await expect(messageBox(page)).toBeVisible();
  await initialBookings;
}

async function showView(page: Page, view: "chat" | "bookings"): Promise<void> {
  const desktopNav = page.getByTestId(`nav-${view}`);
  const mobileTab = page.getByTestId(`tab-${view}`);
  if (await desktopNav.isVisible()) {
    await desktopNav.click();
  } else {
    await mobileTab.click();
  }
  if (view === "bookings") {
    await expect(page.getByTestId("bookings-table")).toBeVisible({ timeout: 15_000 });
  } else {
    await expect(messageBox(page)).toBeVisible({ timeout: 15_000 });
  }
}

async function showBookings(page: Page): Promise<void> {
  await showView(page, "bookings");
}

async function sendMessage(page: Page, text: string): Promise<{ status: number; body: ChatResponse }> {
  const composer = messageBox(page);
  await composer.fill(text);

  const responsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      new URL(response.url()).pathname === apiPath('api/chat'),
  );

  const button = sendButton(page);
  if ((await button.count()) > 0 && (await button.isVisible())) {
    await button.click();
  } else {
    await composer.press('Enter');
  }

  const response = await responsePromise;
  const body = (await response.json()) as ChatResponse;
  return { status: response.status(), body };
}

async function listBookings(page: Page): Promise<Booking[]> {
  const response: APIResponse = await page.request.get(apiPath('api/bookings'));
  expect(response.status()).toBe(200);
  return (await response.json()) as Booking[];
}

type BookingsGate = {
  held: Promise<void>;
  release: () => void;
  dispose: () => Promise<void>;
};

/**
 * Hold the first bookings refetch so the test can prove the UI does not add a
 * row optimistically from a chat event before the database list is returned.
 */
async function holdNextBookingsFetch(page: Page): Promise<BookingsGate> {
  let release!: () => void;
  const released = new Promise<void>((resolve) => {
    release = resolve;
  });
  let heldResolve!: () => void;
  const held = new Promise<void>((resolve) => {
    heldResolve = resolve;
  });

  let captured = false;
  const handler = async (route: Route): Promise<void> => {
    const request = route.request();
    if (
      !captured &&
      request.method() === 'GET' &&
      new URL(request.url()).pathname === apiPath('api/bookings')
    ) {
      captured = true;
      heldResolve();
      await released;
    }
    await route.continue();
  };

  await page.route('**/api/bookings', handler);
  return {
    held,
    release,
    dispose: async () => {
      release();
      await page.unroute('**/api/bookings', handler);
    },
  };
}

test.describe.configure({ mode: 'serial' });

test('prefix routing and unauthenticated API guards', async ({ request }) => {
  const wrongPrefix = await request.get('/nope/');
  expect(wrongPrefix.status()).toBe(404);
  expect(wrongPrefix.headers()['content-type'] ?? '').toContain('application/json');
  const wrongBody = (await wrongPrefix.json()) as { error?: { code?: string } };
  expect(wrongBody.error?.code).toBe('not_found');

  // The frozen contract requires every path outside the runtime prefix to be
  // a 404, including unprefixed API paths.
  const unprefixed = await request.get('/api/bookings');
  expect(unprefixed.status()).toBe(404);
  expect(unprefixed.headers()['content-type'] ?? '').toContain('application/json');

  const prefixedWithoutCookie = await request.get(apiPath('api/bookings'));
  expect(prefixedWithoutCookie.status()).toBe(401);
  expect(prefixedWithoutCookie.headers()['content-type'] ?? '').toContain(
    'application/json',
  );
});

test('login, draft, confirmation and bookings table update', async ({ page }) => {
  await login(page);

  const baseline = (await listBookings(page)).length;

  const first = await sendMessage(page, 'I need a knee consultation');
  expect(first.status).toBe(200);
  expect(first.body.booking_draft?.doctor_id).toBe('D104');
  expect(first.body.booking_draft?.treatment_id).toBe('T005');
  expect(first.body.booking_draft?.local_date).toBe(EXPECTED_DATE);
  expect(first.body.booking_draft?.local_time).toBe(EXPECTED_TIME);
  expect(first.body.booking_draft?.status).toBe('awaiting_confirmation');

  await expect(page.getByText(EXPECTED_DOCTOR).first()).toBeVisible();
  await expect(page.getByText(EXPECTED_TREATMENT).first()).toBeVisible();

  const gate = await holdNextBookingsFetch(page);
  try {
    const confirmation = await sendMessage(page, 'yes');
    expect(confirmation.status).toBe(200);

    const created = confirmation.body.events.find(
      (event) => event.type === 'booking_created',
    );
    const createdBookingId = created?.booking?.booking_id;
    if (!createdBookingId) {
      throw new Error('confirmation response did not include a booking_created event');
    }

    await showBookings(page);

    // If a refetch is in flight, give an optimistic renderer ample time to show
    // its bug before we release the real database response.
    await Promise.race([
      gate.held,
      page.waitForTimeout(3_000),
    ]);
    await page.waitForTimeout(750);
    expect(await bookingRows(page).count()).toBe(baseline);

    gate.release();

    const bookedRow = bookingRows(page)
      .filter({ hasText: EXPECTED_TREATMENT })
      .filter({ hasText: /2030/ });
    await expect(bookedRow.first()).toBeVisible({ timeout: 15_000 });
    expect(await bookingRows(page).count()).toBe(baseline + 1);

    const refresh = page
      .getByTestId('bookings-refresh')
      .or(page.getByTestId('refresh-bookings'))
      .or(page.getByRole('button', { name: /refresh/i }))
      .first();
    await expect(refresh).toBeVisible();
    const refreshed = page.waitForResponse(
      (response) =>
        response.request().method() === 'GET' &&
        new URL(response.url()).pathname === apiPath('api/bookings'),
    );
    await refresh.click();
    await refreshed;
    await expect(bookedRow.first()).toBeVisible();

    const bookings = await listBookings(page);
    const persisted = bookings.find((booking) => booking.booking_id === createdBookingId);
    if (!persisted) {
      throw new Error('created booking was not returned by GET /api/bookings');
    }
    expect(persisted.doctor_id).toBe('D104');
    expect(persisted.treatment_id).toBe('T005');
    expect(persisted.local_date).toBe(EXPECTED_DATE);
    expect(persisted.local_time).toMatch(/^15:00/);

    mkdirSync(path.dirname(STATE_FILE), { recursive: true });
    writeFileSync(STATE_FILE, JSON.stringify(persisted), 'utf8');
  } finally {
    await gate.dispose();
  }
});

test('booking persists across an application restart', async ({ page }) => {
  if (!existsSync(STATE_FILE)) {
    throw new Error(
      `no persisted booking state at ${STATE_FILE}; run the browser flow first and restart the app before this spec`,
    );
  }

  const expected = JSON.parse(readFileSync(STATE_FILE, 'utf8')) as Booking;

  await login(page);
  await showBookings(page);

  const bookings = await listBookings(page);
  const persisted = bookings.find((booking) => booking.booking_id === expected.booking_id);
  if (!persisted) {
    throw new Error(`booking ${expected.booking_id} did not survive the restart`);
  }
  expect(persisted.doctor_id).toBe(expected.doctor_id);
  expect(persisted.treatment_id).toBe(expected.treatment_id);
  expect(persisted.local_date).toBe(expected.local_date);
  expect(persisted.local_time).toBe(expected.local_time);

  const row = bookingRows(page)
    .filter({ hasText: expected.treatment_name })
    .filter({ hasText: /2030/ });
  await expect(row.first()).toBeVisible({ timeout: 15_000 });
});

test('logout revokes the browser session', async ({ page }) => {
  await login(page);

  const before = await page.request.get(apiPath('api/bookings'));
  expect(before.status()).toBe(200);

  const logout = page
    .getByTestId('logout')
    .or(page.getByRole('button', { name: /log ?out|sign out/i }))
    .or(page.getByRole('link', { name: /log ?out|sign out/i }))
    .first();
  await logout.click();

  await expect(
    page.getByTestId('login-password').or(page.getByLabel(/password/i)).first(),
  ).toBeVisible();

  const after = await page.request.get(apiPath('api/bookings'));
  expect(after.status()).toBe(401);
});
