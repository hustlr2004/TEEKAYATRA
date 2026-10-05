export type Role = 'caregiver' | 'asha' | 'manager' | 'admin';

export type DoseStatus = 'completed' | 'due' | 'catch_up' | 'upcoming';

export interface DoseDue {
  code: string;
  name: string;
  window_id: string;
  window_label: string;
  due_from: string;
  due_until: string;
  status: DoseStatus;
  catch_up_bonus: boolean;
}

export interface Child {
  id: number;
  display_name: string;
  birth_date: string;
  district: string;
  village_code: string;
  caregiver_id: number;
  district_is_je_endemic: boolean;
  paper_card_ref?: string | null;
}

export interface ChildJourney {
  child: Child;
  doses: DoseDue[];
  badges: string[];
  next_action?: DoseDue | null;
}

export interface LeaderboardRow {
  village_code: string;
  completed_count: number;
  catch_up_count: number;
  due_count: number;
  score: number;
}

export interface LocalChild {
  id: number;
  dob: string;
  sex: string;
  village_id: number;
  guardian_id: number;
  asha_id: number;
  opt_in_sms: boolean;
  opt_in_ivr: boolean;
  opt_in_app: boolean;
  client_updated_at?: string | null;
  conflict_flag?: boolean;
}

export interface LocalSchedule {
  vaccine_code: string;
  name: string;
  age_due_days: number;
  window_days: number;
  endemic_only: boolean;
}

export interface PendingDose {
  client_uuid: string;
  child_id: number;
  vaccine_code: string;
  given_on: string;
  batch_no?: string | null;
  session_id?: number | null;
  source: 'app' | 'paper' | 'register';
  client_updated_at: string;
  status: 'pending' | 'synced' | 'conflict';
}

export interface SyncState {
  id: 'main';
  lastPulledAt?: string;
  pendingCount: number;
  conflictCount: number;
  lastError?: string;
}
