import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Award,
  Bell,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  Languages,
  Leaf,
  MapPin,
  Navigation,
  PhoneCall,
  ScanLine,
  ShieldCheck,
  TriangleAlert,
  TreePine,
  Volume2,
  WifiOff
} from 'lucide-react';
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { loadSyncState, queueDose, refreshSyncCounts, registerServiceWorker } from './offline';
import type { SyncState } from './types';
import './styles.css';

type Lang = 'en' | 'hi' | 'pa';
type Stage = 1 | 2 | 3 | 4 | 5;

const copy = {
  en: {
    app: 'Teeka Yatra',
    subtitle: 'Your child’s vaccine journey',
    phone: 'Phone number',
    otp: 'OTP',
    sendOtp: 'Send OTP',
    login: 'Log in',
    mockOtp: 'Use 123456 for this demo',
    childCard: 'Child card',
    todayVisits: 'Today’s visits',
    defaulters: 'Overdue follow-up',
    recordDose: 'Record dose',
    scanOrEnter: 'Scan or enter child ID',
    vaccine: 'Vaccine',
    batch: 'Batch number',
    saveDose: 'Save dose',
    attendance: 'Session attendance',
    paperCard: 'Paper card updated',
    pendingSync: 'Pending sync',
    call: 'Call',
    navigate: 'Navigate',
    priority: 'Priority',
    ownProgress: 'My points and badges',
    nextDue: 'Next vaccine',
    dueDate: 'Due date',
    progress: 'Progress',
    points: 'Points',
    badges: 'Badges',
    nearestSession: 'Nearest session',
    remindMe: 'Remind me',
    reminderSet: 'Reminder saved on this phone',
    read: 'Read aloud',
    offline: 'Works offline. Saved reminders stay on this phone.',
    safe: 'On time',
    soon: 'Due soon',
    urgent: 'Catch-up support',
    tree: 'Suraksha Tree',
    lang: 'Language',
    consentTitle: 'Consent and privacy',
    consentStore: 'I consent to store my child record for immunisation support.',
    consentReminders: 'I consent to SMS/IVR reminders. I can reply STOP anytime.',
    consentNeeded: 'Consent is needed before login in this demo.',
    grievance: 'Grievance form',
    grievanceText: 'Tell us what needs correction or support',
    submitGrievance: 'Submit grievance',
    grievanceSaved: 'Grievance saved locally for sync',
    exportData: 'Export my data',
    deleteData: 'Delete my data'
  },
  hi: {
    app: 'टीका यात्रा',
    subtitle: 'आपके बच्चे की टीका यात्रा',
    phone: 'फोन नंबर',
    otp: 'ओटीपी',
    sendOtp: 'ओटीपी भेजें',
    login: 'लॉग इन',
    mockOtp: 'डेमो में 123456 डालें',
    childCard: 'बच्चे का कार्ड',
    todayVisits: 'आज की मुलाकातें',
    defaulters: 'बाकी बच्चों से संपर्क',
    recordDose: 'टीका दर्ज करें',
    scanOrEnter: 'बच्चे की आईडी स्कैन या लिखें',
    vaccine: 'टीका',
    batch: 'बैच नंबर',
    saveDose: 'सेव करें',
    attendance: 'सत्र उपस्थिति',
    paperCard: 'पेपर कार्ड अपडेट',
    pendingSync: 'सिंक बाकी',
    call: 'कॉल',
    navigate: 'रास्ता',
    priority: 'प्राथमिकता',
    ownProgress: 'मेरे अंक और बैज',
    nextDue: 'अगला टीका',
    dueDate: 'तारीख',
    progress: 'प्रगति',
    points: 'अंक',
    badges: 'बैज',
    nearestSession: 'नजदीकी सत्र',
    remindMe: 'याद दिलाएं',
    reminderSet: 'याद दिलाने की सूचना इस फोन पर सेव हो गई',
    read: 'सुनें',
    offline: 'ऑफलाइन भी चलेगा। याद दिलाने की सूचना इसी फोन में रहेगी।',
    safe: 'समय पर',
    soon: 'जल्द टीका',
    urgent: 'कैच-अप सहायता',
    tree: 'सुरक्षा वृक्ष',
    lang: 'भाषा',
    consentTitle: 'सहमति और गोपनीयता',
    consentStore: 'मैं टीकाकरण सहायता के लिए बच्चे का रिकॉर्ड रखने की सहमति देती/देता हूं।',
    consentReminders: 'मैं SMS/IVR याद दिलाने की सहमति देती/देता हूं। STOP भेजकर रोक सकते हैं।',
    consentNeeded: 'इस डेमो में लॉगिन से पहले सहमति जरूरी है।',
    grievance: 'शिकायत फॉर्म',
    grievanceText: 'कृपया बताएं क्या सुधार या सहायता चाहिए',
    submitGrievance: 'शिकायत भेजें',
    grievanceSaved: 'शिकायत सिंक के लिए सेव हो गई',
    exportData: 'मेरा डेटा एक्सपोर्ट करें',
    deleteData: 'मेरा डेटा हटाएं'
  },
  pa: {
    app: 'ਟੀਕਾ ਯਾਤਰਾ',
    subtitle: 'ਤੁਹਾਡੇ ਬੱਚੇ ਦੀ ਟੀਕਾ ਯਾਤਰਾ',
    phone: 'ਫੋਨ ਨੰਬਰ',
    otp: 'ਓਟੀਪੀ',
    sendOtp: 'ਓਟੀਪੀ ਭੇਜੋ',
    login: 'ਲਾਗ ਇਨ',
    mockOtp: 'ਡੈਮੋ ਲਈ 123456 ਵਰਤੋ',
    childCard: 'ਬੱਚੇ ਦਾ ਕਾਰਡ',
    todayVisits: 'ਅੱਜ ਦੀਆਂ ਮੁਲਾਕਾਤਾਂ',
    defaulters: 'ਬਕਾਇਆ ਫਾਲੋ-ਅਪ',
    recordDose: 'ਟੀਕਾ ਦਰਜ ਕਰੋ',
    scanOrEnter: 'ਬੱਚੇ ਦੀ ਆਈਡੀ ਸਕੈਨ ਜਾਂ ਲਿਖੋ',
    vaccine: 'ਟੀਕਾ',
    batch: 'ਬੈਚ ਨੰਬਰ',
    saveDose: 'ਸੇਵ ਕਰੋ',
    attendance: 'ਸੈਸ਼ਨ ਹਾਜ਼ਰੀ',
    paperCard: 'ਪੇਪਰ ਕਾਰਡ ਅਪਡੇਟ',
    pendingSync: 'ਸਿੰਕ ਬਾਕੀ',
    call: 'ਕਾਲ',
    navigate: 'ਰਸਤਾ',
    priority: 'ਤਰਜੀਹ',
    ownProgress: 'ਮੇਰੇ ਅੰਕ ਤੇ ਬੈਜ',
    nextDue: 'ਅਗਲਾ ਟੀਕਾ',
    dueDate: 'ਤਾਰੀਖ',
    progress: 'ਤਰੱਕੀ',
    points: 'ਅੰਕ',
    badges: 'ਬੈਜ',
    nearestSession: 'ਨੇੜਲਾ ਸੈਸ਼ਨ',
    remindMe: 'ਯਾਦ ਦਿਵਾਓ',
    reminderSet: 'ਯਾਦ ਦਿਹਾਨੀ ਇਸ ਫੋਨ ਤੇ ਸੇਵ ਹੋ ਗਈ',
    read: 'ਸੁਣੋ',
    offline: 'ਆਫਲਾਈਨ ਵੀ ਚੱਲਦਾ ਹੈ। ਯਾਦ ਦਿਹਾਨੀ ਇਸੇ ਫੋਨ ਤੇ ਰਹੇਗੀ।',
    safe: 'ਸਮੇਂ ਤੇ',
    soon: 'ਜਲਦੀ ਟੀਕਾ',
    urgent: 'ਕੈਚ-ਅਪ ਸਹਾਇਤਾ',
    tree: 'ਸੁਰੱਖਿਆ ਰੁੱਖ',
    lang: 'ਭਾਸ਼ਾ',
    consentTitle: 'ਸਹਿਮਤੀ ਅਤੇ ਗੋਪਨੀਯਤਾ',
    consentStore: 'ਮੈਂ ਟੀਕਾਕਰਨ ਸਹਾਇਤਾ ਲਈ ਬੱਚੇ ਦਾ ਰਿਕਾਰਡ ਰੱਖਣ ਲਈ ਸਹਿਮਤ ਹਾਂ।',
    consentReminders: 'ਮੈਂ SMS/IVR ਯਾਦ ਦਿਹਾਨੀ ਲਈ ਸਹਿਮਤ ਹਾਂ। STOP ਭੇਜ ਕੇ ਰੋਕ ਸਕਦੇ ਹੋ।',
    consentNeeded: 'ਇਸ ਡੈਮੋ ਵਿੱਚ ਲਾਗਇਨ ਤੋਂ ਪਹਿਲਾਂ ਸਹਿਮਤੀ ਲਾਜ਼ਮੀ ਹੈ।',
    grievance: 'ਸ਼ਿਕਾਇਤ ਫਾਰਮ',
    grievanceText: 'ਦੱਸੋ ਕੀ ਸੋਧ ਜਾਂ ਸਹਾਇਤਾ ਚਾਹੀਦੀ ਹੈ',
    submitGrievance: 'ਸ਼ਿਕਾਇਤ ਭੇਜੋ',
    grievanceSaved: 'ਸ਼ਿਕਾਇਤ ਸਿੰਕ ਲਈ ਸੇਵ ਹੋ ਗਈ',
    exportData: 'ਮੇਰਾ ਡਾਟਾ ਐਕਸਪੋਰਟ ਕਰੋ',
    deleteData: 'ਮੇਰਾ ਡਾਟਾ ਮਿਟਾਓ'
  }
} satisfies Record<Lang, Record<string, string>>;

const child = {
  name: 'Aarohi',
  age: '10 months',
  nextVaccine: 'MR-1 + PCV Booster',
  dueDate: '12 Oct 2026',
  progress: 64,
  points: 146,
  stage: 3 as Stage,
  session: 'Anganwadi Centre, Kankarbagh',
  sessionTime: 'Today, 10:00 AM - 1:00 PM',
  badges: ['First Step', 'Catch-up Champion', 'Paper Card Ready']
};

const visits = [
  { id: 1042, name: 'Aarohi', caregiver: 'Maya', priority: 1, status: 'urgent' as const, vaccine: 'MR-1', due: '12 Oct', phone: '+919000001111', place: 'Lane 4, Kankarbagh' },
  { id: 1088, name: 'Kabir', caregiver: 'Simran', priority: 2, status: 'soon' as const, vaccine: 'Pentavalent-2', due: 'Today', phone: '+919000002222', place: 'Near PHC road' },
  { id: 1101, name: 'Noor', caregiver: 'Harpreet', priority: 3, status: 'safe' as const, vaccine: 'BCG', due: 'Today', phone: '+919000003333', place: 'Anganwadi cluster B' }
].sort((a, b) => a.priority - b.priority);

const ashaBadges = ['Same-day Entry', 'Defaulter Traced', 'Session Ready'];

const managerBlocks = [
  { block: 'Kankarbagh', coverage: 82, dropout: 12, timeliness: 74, zeroDose: 3, quality: 93, sameDay: 81 },
  { block: 'Phulwari', coverage: 68, dropout: 24, timeliness: 61, zeroDose: 8, quality: 86, sameDay: 72 },
  { block: 'Rajgir', coverage: 91, dropout: 6, timeliness: 88, zeroDose: 1, quality: 97, sameDay: 90 }
];

const managerTrend = [
  { month: 'May', coverage: 62, timeliness: 58 },
  { month: 'Jun', coverage: 68, timeliness: 63 },
  { month: 'Jul', coverage: 71, timeliness: 67 },
  { month: 'Aug', coverage: 77, timeliness: 70 },
  { month: 'Sep', coverage: 81, timeliness: 76 }
];

const managerAlerts = [
  {
    severity: 'high',
    block: 'Phulwari',
    text: 'BCG stock use is higher than recorded doses and external register count.',
    action: 'Hold extra outreach session in Phulwari and reconcile paper/register entries.'
  },
  {
    severity: 'medium',
    block: 'Kankarbagh',
    text: 'Penta-1 to Penta-3 dropout is rising.',
    action: 'Ask ASHAs to trace children due for Penta-3 this week.'
  }
];

function App() {
  const [lang, setLang] = useState<Lang>(() => (localStorage.getItem('teeka-lang') as Lang) || 'en');
  const [loggedIn, setLoggedIn] = useState(localStorage.getItem('teeka-login') === 'yes');
  const [phone, setPhone] = useState(localStorage.getItem('teeka-phone') || '');
  const [otp, setOtp] = useState('');
  const [reminded, setReminded] = useState(localStorage.getItem('teeka-reminder') === 'yes');
  const [consentStore, setConsentStore] = useState(localStorage.getItem('teeka-consent-store') === 'yes');
  const [consentReminders, setConsentReminders] = useState(localStorage.getItem('teeka-consent-reminders') === 'yes');
  const [offline, setOffline] = useState(!navigator.onLine);
  const [syncState, setSyncState] = useState<SyncState>({ id: 'main', pendingCount: 0, conflictCount: 0 });
  const t = copy[lang];

  useEffect(() => {
    registerServiceWorker();
    loadSyncState().then(setSyncState).catch(() => undefined);
    const update = () => setOffline(!navigator.onLine);
    window.addEventListener('online', update);
    window.addEventListener('offline', update);
    return () => {
      window.removeEventListener('online', update);
      window.removeEventListener('offline', update);
    };
  }, []);

  useEffect(() => {
    localStorage.setItem('teeka-lang', lang);
  }, [lang]);

  const readText = useMemo(
    () => `${t.app}. ${child.name}. ${t.nextDue}: ${child.nextVaccine}. ${t.dueDate}: ${child.dueDate}. ${t.nearestSession}: ${child.session}, ${child.sessionTime}.`,
    [t]
  );

  if (!loggedIn) {
    return (
      <main className="min-h-screen bg-[#f7faf8] px-4 py-5 text-slate-950">
        <div className="mx-auto grid max-w-md gap-4">
          <TopBar lang={lang} setLang={setLang} />
          <section className="rounded-md border border-slate-200 bg-white p-5 shadow-sm">
            <div className="mb-5 flex items-center gap-3">
              <div className="grid h-14 w-14 place-items-center rounded-md bg-teal-700 text-white">
                <ShieldCheck className="h-8 w-8" aria-hidden="true" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-[#0f3f3b]">{t.app}</h1>
                <p className="text-sm font-medium text-slate-700">{t.subtitle}</p>
              </div>
            </div>
            <label className="grid gap-2 text-sm font-semibold text-slate-800">
              {t.phone}
              <input className="h-12 rounded-md border border-slate-400 px-3 text-lg" inputMode="tel" value={phone} onChange={event => setPhone(event.target.value)} placeholder="+91 90000 00000" />
            </label>
            <button className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-md bg-teal-700 px-4 py-3 text-base font-bold text-white" type="button">
              {t.sendOtp}
            </button>
            <label className="mt-4 grid gap-2 text-sm font-semibold text-slate-800">
              {t.otp}
              <input className="h-12 rounded-md border border-slate-400 px-3 text-lg" inputMode="numeric" value={otp} onChange={event => setOtp(event.target.value)} />
            </label>
            <p className="mt-2 text-sm font-medium text-slate-700">{t.mockOtp}</p>
            <section className="mt-4 rounded-md border border-teal-200 bg-teal-50 p-3">
              <h2 className="mb-2 inline-flex items-center gap-2 text-base font-black text-teal-950">
                <ShieldCheck className="h-5 w-5" aria-hidden="true" />
                {t.consentTitle}
              </h2>
              <label className="mb-2 flex items-start gap-3 text-sm font-bold text-slate-900">
                <input className="mt-1 h-5 w-5" type="checkbox" checked={consentStore} onChange={event => {
                  setConsentStore(event.target.checked);
                  localStorage.setItem('teeka-consent-store', event.target.checked ? 'yes' : 'no');
                }} />
                <span>{t.consentStore}</span>
              </label>
              <label className="flex items-start gap-3 text-sm font-bold text-slate-900">
                <input className="mt-1 h-5 w-5" type="checkbox" checked={consentReminders} onChange={event => {
                  setConsentReminders(event.target.checked);
                  localStorage.setItem('teeka-consent-reminders', event.target.checked ? 'yes' : 'no');
                }} />
                <span>{t.consentReminders}</span>
              </label>
            </section>
            <button
              className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-md bg-[#174ea6] px-4 py-3 text-base font-bold text-white disabled:bg-slate-400"
              disabled={otp !== '123456' || !consentStore}
              type="button"
              onClick={() => {
                localStorage.setItem('teeka-login', 'yes');
                localStorage.setItem('teeka-phone', phone);
                setLoggedIn(true);
              }}
            >
              {t.login}
              <ChevronRight className="h-5 w-5" aria-hidden="true" />
            </button>
            {!consentStore && <p className="mt-2 text-sm font-bold text-red-800">{t.consentNeeded}</p>}
          </section>
          <OfflineNote offline={offline} text={t.offline} />
        </div>
      </main>
    );
  }

  return (
    <ManagerDashboard lang={lang} setLang={setLang} offline={offline} />
  );
}

function ManagerDashboard({ lang, setLang, offline }: { lang: Lang; setLang: (lang: Lang) => void; offline: boolean }) {
  const t = copy[lang];
  return (
    <main className="min-h-screen bg-[#f7faf8] pb-6 text-slate-950">
      <div className="mx-auto grid max-w-5xl gap-4 px-4 py-4">
        <TopBar lang={lang} setLang={setLang} />
        <OfflineNote offline={offline} text="Aggregated manager dashboard. No child names or phone numbers are shown." />
        <section className="rounded-md border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-bold uppercase text-teal-800">Programme manager</p>
              <h1 className="text-3xl font-black text-[#0b352f]">Immunisation analytics</h1>
            </div>
            <button className="rounded-md bg-[#174ea6] px-4 py-3 font-bold text-white" type="button" onClick={exportManagerCsv}>
              Export CSV
            </button>
          </div>
        </section>

        <section className="grid gap-3 sm:grid-cols-4">
          <InfoTile icon={<ShieldCheck />} label="Coverage" value="80%" tone="green" />
          <InfoTile icon={<CalendarDays />} label="Timely" value="74%" tone="blue" />
          <InfoTile icon={<TriangleAlert />} label="Zero-dose" value="12" tone="blue" />
          <InfoTile icon={<Award />} label="Quality" value="92%" tone="green" />
        </section>

        <section className="rounded-md border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="mb-3 text-xl font-black text-[#0b352f]">Coverage heat table by block</h2>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200">
                  <th className="p-2">Block</th>
                  <th className="p-2">Coverage</th>
                  <th className="p-2">Dropout</th>
                  <th className="p-2">Timeliness</th>
                  <th className="p-2">Zero-dose</th>
                  <th className="p-2">Same-day</th>
                </tr>
              </thead>
              <tbody>
                {managerBlocks.map(row => (
                  <tr key={row.block} className="border-b border-slate-100">
                    <td className="p-2 font-bold">{row.block}</td>
                    <HeatCell value={row.coverage} highGood />
                    <HeatCell value={row.dropout} />
                    <HeatCell value={row.timeliness} highGood />
                    <td className="p-2 font-bold">{row.zeroDose}</td>
                    <HeatCell value={row.sameDay} highGood />
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-2">
          <ChartCard title="Coverage trend">
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={managerTrend}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="month" />
                <YAxis domain={[0, 100]} />
                <Tooltip />
                <Line type="monotone" dataKey="coverage" stroke="#166534" strokeWidth={3} />
                <Line type="monotone" dataKey="timeliness" stroke="#174ea6" strokeWidth={3} />
              </LineChart>
            </ResponsiveContainer>
          </ChartCard>
          <ChartCard title="Dropout by block">
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={managerBlocks}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="block" />
                <YAxis domain={[0, 30]} />
                <Tooltip />
                <Bar dataKey="dropout" fill="#b45309" />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
        </section>

        <section className="rounded-md border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="mb-3 text-xl font-black text-[#0b352f]">Mismatch alerts</h2>
          <div className="grid gap-3">
            {managerAlerts.map(alert => (
              <article key={`${alert.block}-${alert.text}`} className="rounded-md border border-amber-300 bg-amber-50 p-3">
                <div className="flex items-start gap-3">
                  <TriangleAlert className="mt-1 h-6 w-6 text-amber-800" aria-hidden="true" />
                  <div>
                    <p className="font-black text-amber-950">{alert.block} · {alert.severity.toUpperCase()}</p>
                    <p className="font-semibold text-slate-800">{alert.text}</p>
                    <p className="mt-2 rounded-md bg-white px-3 py-2 font-bold text-slate-950">{alert.action}</p>
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>
        <ResponsibleDesignPanel t={t} phone={localStorage.getItem('teeka-phone') || ''} />
      </div>
    </main>
  );
}

function ResponsibleDesignPanel({ t, phone }: { t: Record<string, string>; phone: string }) {
  const [message, setMessage] = useState('');
  const [saved, setSaved] = useState(false);

  function saveGrievance() {
    const existing = JSON.parse(localStorage.getItem('teeka-grievances') || '[]') as Array<{ message: string; ts: string }>;
    localStorage.setItem('teeka-grievances', JSON.stringify([...existing, { message, ts: new Date().toISOString() }]));
    setSaved(true);
    setMessage('');
  }

  function exportLocalData() {
    const payload = {
      phone,
      consentStore: localStorage.getItem('teeka-consent-store') === 'yes',
      consentReminders: localStorage.getItem('teeka-consent-reminders') === 'yes',
      reminder: localStorage.getItem('teeka-reminder') === 'yes',
      grievances: JSON.parse(localStorage.getItem('teeka-grievances') || '[]')
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'teeka-yatra-my-data.json';
    link.click();
    URL.revokeObjectURL(url);
  }

  function deleteLocalData() {
    ['teeka-phone', 'teeka-login', 'teeka-reminder', 'teeka-grievances', 'teeka-consent-store', 'teeka-consent-reminders'].forEach(key => localStorage.removeItem(key));
    window.location.reload();
  }

  return (
    <section className="rounded-md border border-teal-200 bg-white p-4 shadow-sm">
      <h2 className="mb-3 inline-flex items-center gap-2 text-xl font-black text-[#0b352f]">
        <ShieldCheck className="h-6 w-6 text-teal-700" aria-hidden="true" />
        {t.consentTitle}
      </h2>
      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
          <label className="grid gap-2 text-sm font-bold text-slate-800">
            {t.grievance}
            <textarea className="min-h-28 rounded-md border border-slate-400 p-3 text-base" value={message} onChange={event => setMessage(event.target.value)} placeholder={t.grievanceText} />
          </label>
          <button className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-md bg-teal-700 px-4 py-3 font-bold text-white disabled:bg-slate-400" type="button" disabled={!message.trim()} onClick={saveGrievance}>
            <ClipboardCheck className="h-5 w-5" aria-hidden="true" />
            {t.submitGrievance}
          </button>
          {saved && <p className="mt-2 text-sm font-bold text-green-800">{t.grievanceSaved}</p>}
        </div>
        <div className="grid content-start gap-3 rounded-md border border-slate-200 bg-slate-50 p-3">
          <button className="inline-flex items-center justify-center gap-2 rounded-md bg-[#174ea6] px-4 py-3 font-bold text-white" type="button" onClick={exportLocalData}>
            <ClipboardCheck className="h-5 w-5" aria-hidden="true" />
            {t.exportData}
          </button>
          <button className="inline-flex items-center justify-center gap-2 rounded-md border border-red-700 bg-red-50 px-4 py-3 font-bold text-red-950" type="button" onClick={deleteLocalData}>
            <TriangleAlert className="h-5 w-5" aria-hidden="true" />
            {t.deleteData}
          </button>
        </div>
      </div>
    </section>
  );
}

function AshaApp({ lang, setLang, offline, syncState, setSyncState }: { lang: Lang; setLang: (lang: Lang) => void; offline: boolean; syncState: SyncState; setSyncState: (state: SyncState) => void }) {
  const t = copy[lang];
  const [childId, setChildId] = useState('1042');
  const [vaccine, setVaccine] = useState('MR_1');
  const [batch, setBatch] = useState('MR-B42');
  const [paperCard, setPaperCard] = useState(true);
  const [attendance, setAttendance] = useState<Record<number, boolean>>({ 1042: true, 1088: false, 1101: true });
  const [saved, setSaved] = useState(false);

  async function saveDose() {
    await queueDose({
      child_id: Number(childId),
      vaccine_code: vaccine,
      given_on: new Date().toISOString().slice(0, 10),
      batch_no: batch,
      session_id: 1,
      source: paperCard ? 'paper' : 'app'
    });
    setSyncState(await refreshSyncCounts());
    setSaved(true);
  }

  return (
    <main className="min-h-screen bg-[#f7faf8] pb-6 text-slate-950">
      <div className="mx-auto grid max-w-md gap-4 px-4 py-4">
        <TopBar lang={lang} setLang={setLang} />
        <OfflineNote offline={offline} text={t.offline} />
        <section className="rounded-md border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-bold uppercase text-teal-800">ASHA</p>
              <h1 className="mt-1 text-3xl font-bold text-[#0b352f]">Sunita Devi</h1>
              <p className="text-base font-semibold text-slate-700">Kankarbagh block</p>
            </div>
            <PendingSyncBadge count={syncState.pendingCount} label={t.pendingSync} />
          </div>
        </section>

        <section className="rounded-md border border-slate-200 bg-white p-4 shadow-sm">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="inline-flex items-center gap-2 text-xl font-bold text-[#0b352f]">
              <CalendarDays className="h-6 w-6 text-teal-700" aria-hidden="true" />
              {t.todayVisits}
            </h2>
            <AudioButton label={t.read} text={`${t.todayVisits}. ${visits.length} children.`} lang={lang} compact />
          </div>
          <div className="grid gap-3">
            {visits.map(visit => (
              <VisitCard key={visit.id} visit={visit} t={t} />
            ))}
          </div>
        </section>

        <section className="rounded-md border border-red-300 bg-red-50 p-4 shadow-sm">
          <div className="mb-3 flex items-center gap-2">
            <Bell className="h-6 w-6 text-red-700" aria-hidden="true" />
            <h2 className="text-lg font-bold text-red-950">{t.defaulters}</h2>
          </div>
          {visits.filter(visit => visit.status === 'urgent').map(visit => (
            <div key={visit.id} className="rounded-md border border-red-200 bg-white p-3">
              <p className="text-lg font-black text-slate-950">{visit.name}</p>
              <p className="font-semibold text-slate-700">{visit.vaccine} · {visit.due}</p>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <a className="inline-flex items-center justify-center gap-2 rounded-md bg-[#174ea6] px-3 py-3 font-bold text-white" href={`tel:${visit.phone}`}>
                  <PhoneCall className="h-5 w-5" aria-hidden="true" />
                  {t.call}
                </a>
                <a className="inline-flex items-center justify-center gap-2 rounded-md bg-teal-700 px-3 py-3 font-bold text-white" href={`https://maps.google.com/?q=${encodeURIComponent(visit.place)}`}>
                  <Navigation className="h-5 w-5" aria-hidden="true" />
                  {t.navigate}
                </a>
              </div>
            </div>
          ))}
        </section>

        <section className="rounded-md border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="mb-3 inline-flex items-center gap-2 text-xl font-bold text-[#0b352f]">
            <ClipboardCheck className="h-6 w-6 text-teal-700" aria-hidden="true" />
            {t.recordDose}
          </h2>
          <div className="grid gap-3">
            <label className="grid gap-2 text-sm font-bold text-slate-800">
              {t.scanOrEnter}
              <div className="grid grid-cols-[1fr_auto] gap-2">
                <input className="h-12 rounded-md border border-slate-400 px-3 text-lg" value={childId} onChange={event => setChildId(event.target.value)} />
                <button className="grid h-12 w-12 place-items-center rounded-md border border-teal-700 bg-teal-50 text-teal-900" type="button" aria-label="scan">
                  <ScanLine className="h-6 w-6" aria-hidden="true" />
                </button>
              </div>
            </label>
            <label className="grid gap-2 text-sm font-bold text-slate-800">
              {t.vaccine}
              <select className="h-12 rounded-md border border-slate-400 px-3 text-lg" value={vaccine} onChange={event => setVaccine(event.target.value)}>
                <option value="MR_1">MR-1</option>
                <option value="PENTA_2">Pentavalent-2</option>
                <option value="BCG">BCG</option>
                <option value="VITA_1">Vitamin A 1</option>
              </select>
            </label>
            <label className="grid gap-2 text-sm font-bold text-slate-800">
              {t.batch}
              <input className="h-12 rounded-md border border-slate-400 px-3 text-lg" value={batch} onChange={event => setBatch(event.target.value)} />
            </label>
            <label className="flex items-center justify-between gap-3 rounded-md border border-slate-300 bg-slate-50 px-3 py-3 text-base font-bold text-slate-900">
              <span>{t.paperCard}</span>
              <input className="h-6 w-6" type="checkbox" checked={paperCard} onChange={event => setPaperCard(event.target.checked)} />
            </label>
            <button className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-[#174ea6] px-4 py-3 text-base font-bold text-white" type="button" onClick={saveDose}>
              <ClipboardCheck className="h-5 w-5" aria-hidden="true" />
              {saved ? `${t.pendingSync}: ${syncState.pendingCount}` : t.saveDose}
            </button>
          </div>
        </section>

        <section className="rounded-md border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="mb-3 text-lg font-bold text-[#0b352f]">{t.attendance}</h2>
          <div className="grid gap-2">
            {visits.map(visit => (
              <label key={visit.id} className="flex items-center justify-between gap-3 rounded-md border border-slate-200 px-3 py-3 font-bold">
                <span>{visit.name}</span>
                <input className="h-6 w-6" type="checkbox" checked={attendance[visit.id] ?? false} onChange={event => setAttendance({ ...attendance, [visit.id]: event.target.checked })} />
              </label>
            ))}
          </div>
        </section>

        <section className="grid grid-cols-2 gap-3">
          <InfoTile icon={<Leaf />} label={t.points} value="284" tone="green" />
          <InfoTile icon={<Award />} label={t.badges} value={String(ashaBadges.length)} tone="blue" />
        </section>
        <section className="rounded-md border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="mb-3 text-lg font-bold text-[#0b352f]">{t.ownProgress}</h2>
          <div className="flex flex-wrap gap-2">
            {ashaBadges.map(badge => (
              <span key={badge} className="inline-flex items-center gap-2 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-bold text-blue-950">
                <Award className="h-4 w-4" aria-hidden="true" />
                {badge}
              </span>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}

function TopBar({ lang, setLang }: { lang: Lang; setLang: (lang: Lang) => void }) {
  return (
    <header className="flex items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <div className="grid h-11 w-11 place-items-center rounded-md bg-teal-700 text-white">
          <ShieldCheck className="h-6 w-6" aria-hidden="true" />
        </div>
        <div>
          <p className="text-lg font-black text-[#0b352f]">{copy[lang].app}</p>
          <p className="text-xs font-bold text-slate-600">{copy[lang].subtitle}</p>
        </div>
      </div>
      <label className="flex items-center gap-2 rounded-md border border-slate-300 bg-white px-2 py-2 text-sm font-bold text-slate-800">
        <Languages className="h-4 w-4" aria-hidden="true" />
        <span className="sr-only">{copy[lang].lang}</span>
        <select className="bg-white text-sm font-bold" value={lang} onChange={event => setLang(event.target.value as Lang)}>
          <option value="en">English</option>
          <option value="hi">हिन्दी</option>
          <option value="pa">ਪੰਜਾਬੀ</option>
        </select>
      </label>
    </header>
  );
}

function AudioButton({ label, text, lang, compact = false }: { label: string; text: string; lang: Lang; compact?: boolean }) {
  return (
    <button className={`inline-flex items-center gap-2 rounded-md border border-teal-700 bg-teal-50 px-3 py-2 text-sm font-bold text-teal-900 ${compact ? 'min-h-10' : 'min-h-12'}`} type="button" onClick={() => speak(text, lang)} aria-label={label}>
      <Volume2 className="h-5 w-5" aria-hidden="true" />
      {label}
    </button>
  );
}

function speak(text: string, lang: Lang) {
  if (!('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = lang === 'hi' ? 'hi-IN' : lang === 'pa' ? 'pa-IN' : 'en-IN';
  window.speechSynthesis.speak(utterance);
}

function OfflineNote({ offline, text }: { offline: boolean; text: string }) {
  return (
    <div className={`flex items-center gap-3 rounded-md border px-3 py-3 text-sm font-bold ${offline ? 'border-red-300 bg-red-50 text-red-950' : 'border-green-300 bg-green-50 text-green-950'}`}>
      {offline ? <WifiOff className="h-5 w-5" aria-hidden="true" /> : <CheckCircle2 className="h-5 w-5" aria-hidden="true" />}
      {text}
    </div>
  );
}

function StatusPill({ status, label }: { status: 'safe' | 'soon' | 'urgent'; label: string }) {
  const styles = {
    safe: 'border-green-300 bg-green-50 text-green-950',
    soon: 'border-amber-300 bg-amber-100 text-amber-950',
    urgent: 'border-red-300 bg-red-50 text-red-950'
  };
  const icons = {
    safe: <CheckCircle2 className="h-4 w-4" aria-hidden="true" />,
    soon: <CalendarDays className="h-4 w-4" aria-hidden="true" />,
    urgent: <Bell className="h-4 w-4" aria-hidden="true" />
  };
  return <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-black ${styles[status]}`}>{icons[status]}{label}</span>;
}

function HeatCell({ value, highGood = false }: { value: number; highGood?: boolean }) {
  const good = highGood ? value >= 80 : value <= 10;
  const warn = highGood ? value >= 60 && value < 80 : value > 10 && value <= 20;
  const style = good
    ? 'bg-green-50 text-green-950'
    : warn
      ? 'bg-amber-100 text-amber-950'
      : 'bg-red-50 text-red-950';
  return <td className={`p-2 font-black ${style}`}>{value}%</td>;
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-md border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="mb-3 text-xl font-black text-[#0b352f]">{title}</h2>
      {children}
    </section>
  );
}

function exportManagerCsv() {
  const header = 'block,coverage,dropout,timeliness,zero_dose,data_quality,same_day_entry';
  const rows = managerBlocks.map(row => [row.block, row.coverage, row.dropout, row.timeliness, row.zeroDose, row.quality, row.sameDay].join(','));
  const blob = new Blob([[header, ...rows].join('\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'teeka-yatra-manager-dashboard.csv';
  link.click();
  URL.revokeObjectURL(url);
}

function PendingSyncBadge({ count, label }: { count: number; label: string }) {
  return (
    <div className="rounded-md border border-amber-300 bg-amber-100 px-3 py-2 text-center text-amber-950">
      <p className="text-2xl font-black">{count}</p>
      <p className="text-xs font-black uppercase">{label}</p>
    </div>
  );
}

function VisitCard({ visit, t }: { visit: (typeof visits)[number]; t: Record<string, string> }) {
  return (
    <article className="rounded-md border border-slate-200 bg-slate-50 p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-xl font-black text-slate-950">{visit.name}</h3>
          <p className="font-semibold text-slate-700">{visit.caregiver} · {visit.vaccine}</p>
          <p className="text-sm font-bold text-slate-600">{visit.place}</p>
        </div>
        <StatusPill status={visit.status} label={`${t.priority} ${visit.priority}`} />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <a className="inline-flex items-center justify-center gap-2 rounded-md border border-blue-700 bg-blue-50 px-3 py-2 font-bold text-blue-950" href={`tel:${visit.phone}`}>
          <PhoneCall className="h-5 w-5" aria-hidden="true" />
          {t.call}
        </a>
        <a className="inline-flex items-center justify-center gap-2 rounded-md border border-teal-700 bg-teal-50 px-3 py-2 font-bold text-teal-950" href={`https://maps.google.com/?q=${encodeURIComponent(visit.place)}`}>
          <Navigation className="h-5 w-5" aria-hidden="true" />
          {t.navigate}
        </a>
      </div>
    </article>
  );
}

function Progress({ value, label }: { value: number; label: string }) {
  return (
    <div className="mt-4">
      <div className="mb-2 flex items-center justify-between text-sm font-bold text-slate-800">
        <span>{label}</span>
        <span>{value}%</span>
      </div>
      <div className="h-4 overflow-hidden rounded-md bg-slate-200" aria-label={`${label} ${value}%`}>
        <div className="h-full rounded-md bg-green-700" style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

function InfoTile({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: string; tone: 'green' | 'blue' }) {
  const color = tone === 'green' ? 'bg-green-700' : 'bg-blue-700';
  return (
    <div className="rounded-md border border-slate-200 bg-white p-4 shadow-sm">
      <div className={`mb-3 grid h-12 w-12 place-items-center rounded-md text-white ${color}`}>{icon}</div>
      <p className="text-sm font-bold text-slate-600">{label}</p>
      <p className="text-3xl font-black text-slate-950">{value}</p>
    </div>
  );
}

function SurakshaTree({ stage }: { stage: Stage }) {
  const canopyScale = [0.45, 0.6, 0.75, 0.9, 1][stage - 1];
  return (
    <svg className="h-64 w-full" viewBox="0 0 320 260" role="img" aria-label={`Suraksha Tree stage ${stage} of 5`}>
      <rect x="0" y="218" width="320" height="24" rx="8" fill="#d9f99d" />
      <path d="M152 110h22l10 112h-42l10-112Z" fill="#8b5e34" />
      <path d="M146 145c-25-5-45-20-60-47" stroke="#8b5e34" strokeWidth="10" strokeLinecap="round" fill="none" />
      <path d="M178 143c23-8 42-25 55-54" stroke="#8b5e34" strokeWidth="10" strokeLinecap="round" fill="none" />
      <g transform={`translate(160 105) scale(${canopyScale}) translate(-160 -105)`}>
        <circle cx="116" cy="104" r="48" fill="#15803d" />
        <circle cx="162" cy="78" r="62" fill="#16a34a" />
        <circle cx="212" cy="108" r="52" fill="#22c55e" />
        <circle cx="160" cy="130" r="58" fill="#15803d" />
      </g>
      {[1, 2, 3, 4, 5].map(item => (
        <g key={item} transform={`translate(${48 + item * 42} 236)`}>
          <circle r="12" fill={item <= stage ? '#166534' : '#cbd5e1'} />
          <text y="4" textAnchor="middle" fontSize="11" fontWeight="800" fill={item <= stage ? '#ffffff' : '#334155'}>{item}</text>
        </g>
      ))}
    </svg>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
