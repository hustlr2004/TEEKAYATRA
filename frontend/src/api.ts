import type { ChildJourney, LeaderboardRow, PendingDose, Role } from './types';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000';

const roleUserId: Record<Role, number> = {
  caregiver: 1,
  asha: 2,
  manager: 3,
  admin: 4
};

const tokenCache: Partial<Record<Role, string>> = {};

async function authHeaders(role: Role): Promise<Record<string, string>> {
  if (!tokenCache[role]) {
    const response = await fetch(`${API_BASE}/auth/token?user_id=${roleUserId[role]}`, { method: 'POST' });
    if (!response.ok) {
      throw new Error(`Auth failed: ${response.status}`);
    }
    tokenCache[role] = (await response.json()).access_token;
  }
  return { Authorization: `Bearer ${tokenCache[role]}` };
}

async function getJson<T>(path: string, role: Role): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: await authHeaders(role)
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function postJson<T>(path: string, body: unknown, role: Role): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(await authHeaders(role))
    },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function fetchJourney(role: Role): Promise<ChildJourney> {
  return getJson<ChildJourney>('/children/1/journey', role);
}

export async function fetchLeaderboard(role: Role): Promise<LeaderboardRow[]> {
  return getJson<LeaderboardRow[]>('/leaderboard/team', role);
}

export async function pushPendingDoses(doses: PendingDose[], role: Role): Promise<{ accepted: string[]; duplicates: string[]; conflicts: Array<{ client_uuid?: string }> }> {
  return postJson('/sync/push', { doses }, role);
}

export async function pullSync(since: string | undefined, role: Role): Promise<unknown> {
  const suffix = since ? `?since=${encodeURIComponent(since)}` : '';
  return getJson(`/sync/pull${suffix}`, role);
}

export async function eventStreamUrl(role: Role, lastEventId?: string): Promise<string> {
  await authHeaders(role);
  const params = new URLSearchParams({ token: tokenCache[role] ?? '' });
  if (lastEventId) {
    params.set('since', lastEventId);
  }
  return `${API_BASE}/events?${params.toString()}`;
}
