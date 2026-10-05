import Dexie, { type Table } from 'dexie';
import type { ChildJourney, LeaderboardRow, LocalChild, LocalSchedule, PendingDose, SyncState } from './types';

const journeyKey = 'teeka-yatra:journey';
const leaderboardKey = 'teeka-yatra:leaderboard';

export function saveJourney(journey: ChildJourney): void {
  localStorage.setItem(journeyKey, JSON.stringify(journey));
}

export function loadJourney(): ChildJourney | null {
  const raw = localStorage.getItem(journeyKey);
  return raw ? (JSON.parse(raw) as ChildJourney) : null;
}

export function saveLeaderboard(rows: LeaderboardRow[]): void {
  localStorage.setItem(leaderboardKey, JSON.stringify(rows));
}

export function loadLeaderboard(): LeaderboardRow[] {
  const raw = localStorage.getItem(leaderboardKey);
  return raw ? (JSON.parse(raw) as LeaderboardRow[]) : [];
}

export function registerServiceWorker(): void {
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/service-worker.js').catch(() => undefined);
    });
  }
}

class TeekaYatraDb extends Dexie {
  children!: Table<LocalChild, number>;
  schedule!: Table<LocalSchedule, string>;
  pendingDoses!: Table<PendingDose, string>;
  syncState!: Table<SyncState, string>;

  constructor() {
    super('teeka-yatra');
    this.version(1).stores({
      children: 'id, village_id, guardian_id, asha_id, conflict_flag',
      schedule: 'vaccine_code, age_due_days',
      pendingDoses: 'client_uuid, child_id, status, client_updated_at',
      syncState: 'id'
    });
  }
}

export const offlineDb = new TeekaYatraDb();

export async function queueDose(dose: Omit<PendingDose, 'client_uuid' | 'client_updated_at' | 'status'>): Promise<PendingDose> {
  const pending: PendingDose = {
    ...dose,
    client_uuid: crypto.randomUUID(),
    client_updated_at: new Date().toISOString(),
    status: 'pending'
  };
  await offlineDb.pendingDoses.put(pending);
  await refreshSyncCounts();
  return pending;
}

export async function pendingDoses(): Promise<PendingDose[]> {
  return offlineDb.pendingDoses.where('status').equals('pending').toArray();
}

export async function savePulledData(payload: { children?: LocalChild[]; schedule?: LocalSchedule[]; conflicts?: unknown[]; server_time?: string }): Promise<void> {
  if (payload.children?.length) {
    await offlineDb.children.bulkPut(payload.children);
  }
  if (payload.schedule?.length) {
    await offlineDb.schedule.bulkPut(payload.schedule);
  }
  await offlineDb.syncState.put({
    id: 'main',
    lastPulledAt: payload.server_time ?? new Date().toISOString(),
    pendingCount: await offlineDb.pendingDoses.where('status').equals('pending').count(),
    conflictCount: payload.conflicts?.length ?? 0
  });
}

export async function markPushed(accepted: string[], duplicates: string[], conflicts: Array<{ client_uuid?: string }>): Promise<void> {
  await Promise.all([...accepted, ...duplicates].map(clientUuid => offlineDb.pendingDoses.update(clientUuid, { status: 'synced' })));
  await Promise.all(conflicts.filter(item => item.client_uuid).map(item => offlineDb.pendingDoses.update(item.client_uuid!, { status: 'conflict' })));
  await refreshSyncCounts();
}

export async function refreshSyncCounts(): Promise<SyncState> {
  const state: SyncState = {
    id: 'main',
    pendingCount: await offlineDb.pendingDoses.where('status').equals('pending').count(),
    conflictCount: await offlineDb.pendingDoses.where('status').equals('conflict').count()
  };
  const previous = await offlineDb.syncState.get('main');
  await offlineDb.syncState.put({ ...previous, ...state });
  return { ...previous, ...state };
}

export async function loadSyncState(): Promise<SyncState> {
  return (await offlineDb.syncState.get('main')) ?? { id: 'main', pendingCount: 0, conflictCount: 0 };
}
