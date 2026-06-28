import { readFileSync, writeFileSync, existsSync } from 'fs';
import http from 'http';

const BASE_URL = 'https://xlerp.xlri.ac.in';
const TOKEN_FILE = '.token.json';

function readToken() {
  try {
    return existsSync(TOKEN_FILE) ? JSON.parse(readFileSync(TOKEN_FILE, 'utf-8')) : null;
  } catch { return null; }
}

function writeToken(data) {
  writeFileSync(TOKEN_FILE, JSON.stringify(data, null, 2));
}

function formatICSDate(date, time) {
  return date.replace(/-/g, '') + 'T' + time.replace(/:/g, '') + '00';
}

function escapeICS(text) {
  if (!text) return '';
  return String(text).replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\n/g, '\\n');
}

function generateICS(sessions, activities) {
  const classEvents = sessions.filter(s => !s.isCancelled).map(s => {
    const course = s.course;
    const faculty = s.faculty;
    const venue = s.venue;
    const desc = [
      `Faculty: ${faculty.prefix || ''} ${faculty.firstName} ${faculty.lastName}`.trim(),
      `Course Code: ${course.courseCode}`,
      `Section: ${s.section.sectionName}`,
      `Type: ${s.courseOfferType}`,
    ].filter(Boolean).join('\\n');
    const location = venue ? `${venue.name} (${venue.building})` : '';
    return [
      'BEGIN:VEVENT',
      `UID:${s.sessionId}@xlri-schedule-sync`,
      `DTSTART:${formatICSDate(s.classDate, s.startTime)}`,
      `DTEND:${formatICSDate(s.classDate, s.endTime)}`,
      `SUMMARY:${escapeICS(course.courseName)}`,
      `DESCRIPTION:${desc}`,
      `LOCATION:${escapeICS(location)}`,
      `CATEGORIES:${escapeICS(course.courseCode)}`,
      'END:VEVENT',
    ].join('\r\n');
  });

  const activityEvents = activities.filter(a => !a.isDeleted).map(a => {
    const venue = a.venue;
    const desc = [
      `Type: ${a.type}`,
      a.batchSection ? `Section: ${a.batchSection.sectionName}` : '',
    ].filter(Boolean).join('\\n');
    const location = venue ? `${venue.name} (${venue.building})` : '';
    return [
      'BEGIN:VEVENT',
      `UID:${a.id}@xlri-schedule-sync`,
      `DTSTART:${formatICSDate(a.date, a.startTime)}`,
      `DTEND:${formatICSDate(a.date, a.endTime)}`,
      `SUMMARY:${escapeICS(a.name)}`,
      `DESCRIPTION:${desc}`,
      `LOCATION:${escapeICS(location)}`,
      'CATEGORIES:Class Activity',
      'END:VEVENT',
    ].join('\r\n');
  });

  return [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//XLRI Schedule Sync//EN',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    ...classEvents,
    ...activityEvents,
    'END:VCALENDAR',
  ].join('\r\n');
}

async function login(email, password) {
  const res = await fetch(`${BASE_URL}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  const data = await res.json();
  if (!data.success) throw new Error(data.message || 'Login failed');
  return data.data;
}

async function fetchSchedule(token, startDate, endDate) {
  const url = `${BASE_URL}/api/v1/schedule/my-schedule/student?startDate=${startDate}&endDate=${endDate}`;
  const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  const data = await res.json();
  if (!data.success) throw new Error(data.message || 'Failed to fetch schedule');
  return data.data;
}

async function fetchClassActivities(token, startDate, endDate) {
  const url = `${BASE_URL}/api/v1/class-activities/my?startDate=${startDate}&endDate=${endDate}`;
  const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  const data = await res.json();
  if (!data.success) throw new Error(data.message || 'Failed to fetch class activities');
  return data.data;
}

function serveStatic(res, status, contentType, body) {
  res.writeHead(status, {
    'Content-Type': contentType,
    'Cache-Control': 'no-store, no-cache, must-revalidate',
  });
  res.end(body);
}

async function handleAPI(req, res) {
  const url = new URL(req.url, 'http://localhost');
  const body = await new Promise(r => { let d = ''; req.on('data', c => d += c); req.on('end', () => r(d)); });

  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }

  try {
    if (url.pathname === '/api/login' && req.method === 'POST') {
      const { email, password } = JSON.parse(body);
      if (!email || !password) { serveStatic(res, 400, 'application/json', JSON.stringify({ error: 'Email and password required' })); return; }
      const loginData = await login(email, password);
      writeToken({ token: loginData.token, expiresAt: Date.now() + 24 * 60 * 60 * 1000 });
      serveStatic(res, 200, 'application/json', JSON.stringify({ success: true }));
      return;
    }

    if (url.pathname === '/api/sync' && req.method === 'POST') {
      const { email, password, startDate, endDate, mode } = JSON.parse(body);
      if (!email || !password) { serveStatic(res, 400, 'application/json', JSON.stringify({ error: 'Email and password required' })); return; }
      const loginData = await login(email, password);
      writeToken({ token: loginData.token, expiresAt: Date.now() + 24 * 60 * 60 * 1000 });

      let sessions = [];
      let activities = [];

      if (mode === 'classes' || mode === 'all' || !mode) {
        sessions = await fetchSchedule(loginData.token, startDate, endDate);
      }
      if (mode === 'activities' || mode === 'all' || !mode) {
        activities = await fetchClassActivities(loginData.token, startDate, endDate);
      }

      const ics = generateICS(sessions, activities);
      serveStatic(res, 200, 'application/json', JSON.stringify({ success: true, sessions, activities, ics }));
      return;
    }
  } catch (err) {
    serveStatic(res, 500, 'application/json', JSON.stringify({ error: err.message }));
  }
}

function serveIndex(res) {
  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>XLRI Schedule Sync</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js"></script>
<style>
:root {
  --bg: #f5f5f5;
  --text: #1a1a1a;
  --text-secondary: #737373;
  --text-muted: #a3a3a3;
  --sidebar-bg: #ffffff;
  --sidebar-text: #737373;
  --sidebar-text-hover: #1a1a1a;
  --sidebar-active-bg: #f0f0f0;
  --sidebar-active-text: #1a1a1a;
  --sidebar-active-border: #1a1a1a;
  --sidebar-border: #e5e5e5;
  --card-bg: #ffffff;
  --card-border: #e5e5e5;
  --card-title: #1a1a1a;
  --label: #737373;
  --input-bg: #ffffff;
  --input-border: #d4d4d4;
  --input-text: #1a1a1a;
  --input-focus-border: #1a1a1a;
  --btn-primary-bg: #1a1a1a;
  --btn-primary-text: #ffffff;
  --btn-primary-hover: #333333;
  --btn-secondary-bg: #f0f0f0;
  --btn-secondary-text: #333333;
  --btn-secondary-hover: #e5e5e5;
  --spinner-border: rgba(255,255,255,.3);
  --spinner-top: #ffffff;
  --status-error-bg: #fef2f2;
  --status-error-text: #991b1b;
  --status-error-border: #fecaca;
  --status-success-bg: #f0fdf4;
  --status-success-text: #166534;
  --status-success-border: #bbf7d0;
  --status-info-bg: #eff6ff;
  --status-info-text: #1e40af;
  --status-info-border: #bfdbfe;
  --table-header-text: #737373;
  --table-header-border: #e5e5e5;
  --table-row-border: #f0f0f0;
  --table-row-hover: #fafafa;
  --count-text: #737373;
  --venue-text: #737373;
  --faculty-text: #525252;
  --badge-core-bg: #e8e8e8;
  --badge-core-text: #1a1a1a;
  --badge-elective-bg: #e8e8e8;
  --badge-elective-text: #1a1a1a;
  --tt-header-bg: #fafafa;
  --tt-header-text: #333333;
  --tt-header-border: #d4d4d4;
  --tt-time-text: #737373;
  --tt-time-border: #e5e5e5;
  --tt-break-bg: #fafafa;
  --tt-break-border: #e5e5e5;
  --tt-break-text: #a3a3a3;
  --tt-legend-bg: #fafafa;
  --tt-void-text: #a3a3a3;
}

[data-theme="dark"] {
  --bg: #000000;
  --text: #e5e5e5;
  --text-secondary: #a3a3a3;
  --text-muted: #525252;
  --sidebar-bg: #000000;
  --sidebar-text: #525252;
  --sidebar-text-hover: #e5e5e5;
  --sidebar-active-bg: #111111;
  --sidebar-active-text: #e5e5e5;
  --sidebar-active-border: #e5e5e5;
  --sidebar-border: #1a1a1a;
  --card-bg: #0a0a0a;
  --card-border: #1a1a1a;
  --card-title: #e5e5e5;
  --label: #737373;
  --input-bg: #0a0a0a;
  --input-border: #262626;
  --input-text: #e5e5e5;
  --input-focus-border: #e5e5e5;
  --btn-primary-bg: #e5e5e5;
  --btn-primary-text: #000000;
  --btn-primary-hover: #cccccc;
  --btn-secondary-bg: #1a1a1a;
  --btn-secondary-text: #a3a3a3;
  --btn-secondary-hover: #262626;
  --spinner-border: rgba(255,255,255,.15);
  --spinner-top: #e5e5e5;
  --status-error-bg: #1a0000;
  --status-error-text: #fca5a5;
  --status-error-border: #3b0000;
  --status-success-bg: #002200;
  --status-success-text: #86efac;
  --status-success-border: #004400;
  --status-info-bg: #001133;
  --status-info-text: #93c5fd;
  --status-info-border: #002266;
  --table-header-text: #737373;
  --table-header-border: #1a1a1a;
  --table-row-border: #111111;
  --table-row-hover: #0d0d0d;
  --count-text: #737373;
  --venue-text: #737373;
  --faculty-text: #a3a3a3;
  --badge-core-bg: #1a1a1a;
  --badge-core-text: #e5e5e5;
  --badge-elective-bg: #1a1a1a;
  --badge-elective-text: #e5e5e5;
  --tt-header-bg: #000000;
  --tt-header-text: #ffffff;
  --tt-header-border: #262626;
  --tt-time-text: #ffffff;
  --tt-time-border: #1a1a1a;
  --tt-break-bg: #000000;
  --tt-break-border: #1a1a1a;
  --tt-break-text: #737373;
  --tt-legend-bg: #000000;
  --tt-void-text: #737373;
}

* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'JetBrains Mono', 'SF Mono', 'Fira Code', 'Menlo', 'Consolas', monospace; background: var(--bg); color: var(--text); min-height: 100vh; display: flex; -webkit-font-smoothing: antialiased; }
.sidebar { width: 200px; height: 100vh; background: var(--sidebar-bg); padding: 32px 0; flex-shrink: 0; display: flex; flex-direction: column; border-right: 1px solid var(--sidebar-border); position: sticky; top: 0; overflow: hidden; }
.sidebar h1 { font-size: 13px; font-weight: 700; color: var(--text); padding: 0 24px; margin-bottom: 32px; text-transform: uppercase; letter-spacing: .08em; }
.sidebar-item { padding: 8px 24px; font-size: 12px; font-weight: 500; color: var(--sidebar-text); cursor: pointer; transition: all .1s; border-left: 2px solid transparent; }
.sidebar-item:hover { color: var(--sidebar-text-hover); }
.sidebar-item.active { color: var(--sidebar-active-text); border-left-color: var(--sidebar-active-border); }
.sidebar-spacer { flex: 1; }
.sidebar-footer { padding: 16px 24px 0; border-top: 1px solid var(--sidebar-border); }
.main { flex: 1; min-width: 0; padding: 40px; }
.card { background: var(--card-bg); border: 1px solid var(--card-border); padding: 28px; margin-bottom: 20px; }
.card h2 { font-size: 13px; font-weight: 600; margin-bottom: 20px; color: var(--card-title); text-transform: uppercase; letter-spacing: .05em; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.form-grid .full { grid-column: 1 / -1; }
label { display: block; font-size: 11px; font-weight: 500; color: var(--label); margin-bottom: 6px; text-transform: uppercase; letter-spacing: .05em; }
input, select { width: 100%; padding: 10px 12px; border: 1px solid var(--input-border); font-size: 13px; font-family: inherit; outline: none; transition: border .15s; background: var(--input-bg); color: var(--input-text); }
input:focus, select:focus { border-color: var(--input-focus-border); }
::placeholder { color: var(--text-muted); opacity: .6; }
.btn { display: inline-flex; align-items: center; gap: 8px; padding: 10px 20px; border: none; font-size: 12px; font-weight: 500; font-family: inherit; cursor: pointer; transition: all .1s; text-transform: uppercase; letter-spacing: .05em; }
.btn-primary { background: var(--btn-primary-bg); color: var(--btn-primary-text); }
.btn-primary:hover { background: var(--btn-primary-hover); }
.btn-primary:disabled { opacity: .35; cursor: not-allowed; }
.btn-secondary { background: var(--btn-secondary-bg); color: var(--btn-secondary-text); }
.btn-secondary:hover { background: var(--btn-secondary-hover); }
.btn-icon { padding: 8px 12px; font-size: 11px; }
.spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid var(--spinner-border); border-top-color: var(--spinner-top); border-radius: 50%; animation: spin .6s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.status { padding: 10px 14px; font-size: 12px; margin-bottom: 16px; display: none; }
.status.error { display: block; background: var(--status-error-bg); color: var(--status-error-text); border: 1px solid var(--status-error-border); }
.status.success { display: block; background: var(--status-success-bg); color: var(--status-success-text); border: 1px solid var(--status-success-border); }
.status.info { display: block; background: var(--status-info-bg); color: var(--status-info-text); border: 1px solid var(--status-info-border); }
.hidden { display: none !important; }
.actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.count { font-size: 11px; color: var(--count-text); margin-bottom: 12px; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
thead th { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--table-header-border); color: var(--table-header-text); font-weight: 600; font-size: 10px; text-transform: uppercase; letter-spacing: .05em; }
tbody td { padding: 8px 10px; border-bottom: 1px solid var(--table-row-border); vertical-align: top; }
tbody tr:hover { background: var(--table-row-hover); }
.badge { display: inline-block; padding: 2px 8px; font-size: 10px; font-weight: 500; letter-spacing: .03em; }
.badge-core { background: var(--badge-core-bg); color: var(--badge-core-text); }
.badge-elective { background: var(--badge-elective-bg); color: var(--badge-elective-text); }
.venue { color: var(--venue-text); font-size: 11px; }
.faculty { color: var(--faculty-text); }

.timetable { margin-top: 16px; overflow-x: auto; }
.timetable-grid { display: grid; min-width: 700px; }
.timetable-header { display: contents; }
.timetable-header > div { padding: 8px; font-size: 11px; font-weight: 600; color: var(--tt-header-text); text-align: center; border-bottom: 1px solid var(--tt-header-border); background: var(--tt-header-bg); position: sticky; top: 0; z-index: 2; }
.timetable-time { font-size: 10px; color: var(--tt-time-text); padding: 0 8px; text-align: right; border-right: 1px solid var(--tt-time-border); display: flex; align-items: center; justify-content: flex-end; }
.session-block { padding: 4px 8px; font-size: 11px; line-height: 1.3; overflow: hidden; border-left: 2px solid; margin: 1px; display: flex; flex-direction: column; justify-content: center; cursor: default; }
.session-block .course-code { font-weight: 600; font-size: 9px; text-transform: uppercase; letter-spacing: .05em; }
.session-block .course-name { font-weight: 500; }
.session-block .session-venue { font-size: 9px; opacity: .6; }
.timetable-break { display: flex; align-items: center; justify-content: center; font-size: 9px; color: var(--tt-break-text); font-weight: 500; letter-spacing: .1em; text-transform: uppercase; border-top: 1px dashed var(--tt-break-border); border-bottom: 1px dashed var(--tt-break-border); background: var(--tt-break-bg); }
.timetable-legend { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 12px; padding: 10px 14px; background: var(--tt-legend-bg); border: 1px solid var(--card-border); font-size: 11px; }
.legend-item { display: flex; align-items: center; gap: 6px; }
.legend-swatch { width: 10px; height: 10px; border-left: 2px solid; flex-shrink: 0; }

.theme-toggle { display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 11px; color: var(--sidebar-text); text-transform: uppercase; letter-spacing: .05em; }
.theme-toggle:hover { color: var(--sidebar-text-hover); }

@media (max-width: 768px) {
  body { flex-direction: column; }
  .sidebar { width: 100%; height: auto; flex-direction: row; padding: 12px 16px; border-right: none; border-bottom: 1px solid var(--sidebar-border); position: sticky; top: 0; overflow: visible; align-items: center; gap: 12px; }
  .sidebar h1 { margin-bottom: 0; font-size: 10px; white-space: nowrap; }
  .sidebar h1 br { display: none; }
  .sidebar-item { padding: 6px 10px; border-left: none; border-bottom: 2px solid transparent; font-size: 11px; white-space: nowrap; }
  .sidebar-item.active { border-left: none; border-bottom-color: var(--sidebar-active-border); }
  .sidebar-spacer { flex: 1; }
  .sidebar-footer { padding: 0; border-top: none; }
  .main { padding: 16px; }
  .card { padding: 16px; }
  .card h2 { margin-bottom: 16px; }
  .form-grid { grid-template-columns: 1fr; }
  .form-grid .full { grid-column: 1; }
  .actions { flex-direction: column; align-items: stretch; }
  .actions .btn { justify-content: center; }
  #icsResults .card > div:first-child { flex-direction: column; align-items: flex-start; gap: 8px; }
  #icsResults .card > div:first-child h2 { margin-bottom: 0; }
  table { font-size: 11px; }
  thead th, tbody td { padding: 6px 8px; }
  #ttHeader { flex-direction: column; align-items: flex-start; gap: 8px; }
}
</style>
</head>
<body>
<div class="sidebar">
  <h1>XLRI Schedule<br>Sync</h1>
  <div class="sidebar-item active" data-view="ics" onclick="switchView('ics')">Download ICS</div>
  <div class="sidebar-item" data-view="timetable" onclick="switchView('timetable')">Get Timetable</div>
  <div class="sidebar-spacer"></div>
  <div class="sidebar-footer">
    <div class="theme-toggle" onclick="toggleTheme()">
      <span id="themeLabel">Dark</span>
    </div>
  </div>
</div>

<div class="main">
  <!-- === ICS VIEW === -->
  <div id="view-ics">
    <div class="card">
      <h2>Login</h2>
      <div class="form-grid">
        <div class="full">
          <label>ERP Email</label>
          <input type="email" id="email" placeholder="bxxxxx@astra.xlri.ac.in" autocomplete="email">
        </div>
        <div class="full">
          <label>ERP Password</label>
          <input type="password" id="password" placeholder="ERP password" autocomplete="current-password">
        </div>
        <div>
          <label>Start Date</label>
          <input type="date" id="startDate">
        </div>
        <div>
          <label>End Date</label>
          <input type="date" id="endDate">
        </div>
        <div class="full">
          <label>Include</label>
          <div style="display:flex;gap:24px;align-items:center;min-height:42px;flex-wrap:nowrap">
            <label style="display:inline-flex;align-items:center;gap:6px;font-size:14px;font-weight:400;cursor:pointer;white-space:nowrap">
              <input type="radio" name="mode" value="classes" onchange="hideICSResults()"> Classes only
            </label>
            <label style="display:inline-flex;align-items:center;gap:6px;font-size:14px;font-weight:400;cursor:pointer;white-space:nowrap">
              <input type="radio" name="mode" value="activities" onchange="hideICSResults()"> Activities only
            </label>
            <label style="display:inline-flex;align-items:center;gap:6px;font-size:14px;font-weight:400;cursor:pointer;white-space:nowrap">
              <input type="radio" name="mode" value="all" checked onchange="hideICSResults()"> Classes + Activities
            </label>
          </div>
        </div>
      </div>
      <div class="actions" style="margin-top:16px">
        <button class="btn btn-primary" id="icsSyncBtn" onclick="syncICS()">Get Schedule</button>
      </div>
    </div>
    <div id="icsStatus"></div>
    <div id="icsResults" class="card hidden">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
        <h2 style="margin-bottom:0">Schedule</h2>
        <button class="btn btn-secondary btn-icon" onclick="downloadICS()">Download ICS</button>
      </div>
      <div class="count" id="icsCount"></div>
      <div style="overflow-x:auto">
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Time</th>
              <th>Title</th>
              <th>Detail</th>
              <th>Venue</th>
              <th>Type</th>
            </tr>
          </thead>
          <tbody id="icsBody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- === TIMETABLE VIEW === -->
  <div id="view-timetable" class="hidden">
    <div class="card">
      <h2>Login</h2>
      <div class="form-grid">
        <div class="full">
          <label>ERP Email</label>
          <input type="email" id="ttEmail" placeholder="bxxxxx@astra.xlri.ac.in" autocomplete="email">
        </div>
        <div class="full">
          <label>ERP Password</label>
          <input type="password" id="ttPassword" placeholder="ERP password" autocomplete="current-password">
        </div>
        <div class="full">
          <label>Date</label>
          <input type="date" id="ttDate">
        </div>
      </div>
      <div class="actions" style="margin-top:16px">
        <button class="btn btn-primary" id="ttBtn" onclick="fetchTimetable()">Get Timetable</button>
      </div>
    </div>
    <div id="ttStatus"></div>
    <div id="ttResults" class="hidden">
      <div id="ttHeader" class="card" style="padding:16px 24px;display:flex;justify-content:space-between;align-items:center">
        <div><strong style="font-size:15px" id="ttTitle"></strong><br><span style="font-size:13px;color:#64748b" id="ttSubtitle"></span></div>
        <button class="btn btn-secondary btn-icon" id="downloadPngBtn" onclick="downloadTimetablePNG()" style="display:none">Download PNG</button>
      </div>
      <div class="card" id="ttCard">
        <div id="ttLegend" class="timetable-legend hidden"></div>
        <div class="timetable" id="ttGrid"></div>
      </div>
    </div>
  </div>
</div>

<script>
// ========== DARK MODE ==========
function getPreferredTheme() {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function setTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('theme', theme);
  document.getElementById('themeLabel').textContent = theme === 'dark' ? 'Light' : 'Dark';
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'light';
  setTheme(current === 'dark' ? 'light' : 'dark');
}

(function initTheme() {
  const stored = localStorage.getItem('theme');
  if (stored) {
    setTheme(stored);
  } else {
    setTheme(getPreferredTheme());
  }
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
    if (!localStorage.getItem('theme')) setTheme(e.matches ? 'dark' : 'light');
  });
})();

const COURSE_PALETTE = [
  { bg: '#e8e8e8', border: '#1a1a1a', text: '#1a1a1a' },
  { bg: '#e0e7ff', border: '#4338ca', text: '#4338ca' },
  { bg: '#d1fae5', border: '#059669', text: '#059669' },
  { bg: '#fce7f3', border: '#db2777', text: '#db2777' },
  { bg: '#fef3c7', border: '#d97706', text: '#d97706' },
  { bg: '#dbeafe', border: '#2563eb', text: '#2563eb' },
  { bg: '#ede9fe', border: '#7c3aed', text: '#7c3aed' },
  { bg: '#ccfbf1', border: '#0d9488', text: '#0d9488' },
  { bg: '#fecaca', border: '#dc2626', text: '#dc2626' },
  { bg: '#f5f5f5', border: '#525252', text: '#525252' },
];

let lastICS = '';
let lastSessions = [];
let lastActivities = [];

function setStatus(elId, type, msg) {
  const el = document.getElementById(elId);
  el.className = 'status ' + type;
  el.textContent = msg;
}

function hideICSResults() {
  document.getElementById('icsResults').classList.add('hidden');
  document.getElementById('icsStatus').className = 'status';
}

function getCourseColor(code) {
  let hash = 0;
  for (let i = 0; i < code.length; i++) hash = ((hash << 5) - hash) + code.charCodeAt(i);
  return COURSE_PALETTE[Math.abs(hash) % COURSE_PALETTE.length];
}

function fmtDate(d) {
  const date = parseLocalDate(d);
  return date.getDate() + ' ' + date.toLocaleString('en', { month: 'short' }) + ' ' + ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][date.getDay()];
}

function fmtTime(t) {
  const [h, m] = t.split(':');
  const hr = parseInt(h);
  return (hr % 12 || 12) + ':' + m + ' ' + (hr >= 12 ? 'pm' : 'am');
}

function timeToMinutes(t) {
  const [h, m] = t.split(':').map(Number);
  return h * 60 + m;
}

function switchView(view) {
  document.querySelectorAll('.sidebar-item').forEach(el => el.classList.remove('active'));
  document.querySelector('[data-view="' + view + '"]').classList.add('active');
  document.getElementById('view-ics').classList.toggle('hidden', view !== 'ics');
  document.getElementById('view-timetable').classList.toggle('hidden', view !== 'timetable');
}

// ========== ICS VIEW ==========

function setDefaultDates() {
  const today = new Date();
  const weekLater = new Date(today);
  weekLater.setDate(today.getDate() + 7);
  document.getElementById('startDate').value = toLocalDateStr(today);
  document.getElementById('endDate').value = toLocalDateStr(weekLater);
  document.getElementById('ttDate').value = toLocalDateStr(today);
}

function renderICSList(sessions, activities) {
  lastSessions = sessions;
  lastActivities = activities;
  const rows = [];
  for (const s of sessions) {
    if (s.isCancelled) continue;
    const c = s.course;
    const f = s.faculty;
    const v = s.venue;
    rows.push('<tr>' +
      '<td>' + fmtDate(s.classDate) + '</td>' +
      '<td>' + fmtTime(s.startTime) + ' – ' + fmtTime(s.endTime) + '</td>' +
      '<td><strong>' + c.courseName + '</strong></td>' +
      '<td class="faculty">' + (f.prefix || '') + ' ' + f.firstName + ' ' + f.lastName + '</td>' +
      '<td class="venue">' + (v ? v.name : '—') + '</td>' +
      '<td><span class="badge badge-core">' + c.courseCode + '</span></td>' +
      '</tr>');
  }
  for (const a of activities) {
    if (a.isDeleted) continue;
    const v = a.venue;
    rows.push('<tr>' +
      '<td>' + fmtDate(a.date) + '</td>' +
      '<td>' + fmtTime(a.startTime) + ' – ' + fmtTime(a.endTime) + '</td>' +
      '<td><strong>' + a.name + '</strong></td>' +
      '<td class="faculty">' + (a.type || '—') + '</td>' +
      '<td class="venue">' + (v ? v.name : '—') + '</td>' +
      '<td><span class="badge badge-elective">Activity</span></td>' +
      '</tr>');
  }
  document.getElementById('icsBody').innerHTML = rows.join('');
  const total = sessions.filter(s => !s.isCancelled).length + activities.filter(a => !a.isDeleted).length;
  document.getElementById('icsCount').textContent = total + ' event' + (total !== 1 ? 's' : '');
}

async function syncICS() {
  const email = document.getElementById('email').value.trim();
  const password = document.getElementById('password').value;
  const startDate = document.getElementById('startDate').value;
  const endDate = document.getElementById('endDate').value;
  const mode = document.querySelector('input[name="mode"]:checked').value;
  if (!email || !password) { setStatus('icsStatus', 'error', 'Please enter email and password'); return; }
  if (!startDate || !endDate) { setStatus('icsStatus', 'error', 'Please select date range'); return; }
  const btn = document.getElementById('icsSyncBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Syncing...';
  try {
    const res = await fetch('/api/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, startDate, endDate, mode }),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || 'Request failed');
    lastICS = data.ics;
    renderICSList(data.sessions || [], data.activities || []);
    document.getElementById('icsResults').classList.remove('hidden');
    const total = (data.sessions || []).filter(s => !s.isCancelled).length + (data.activities || []).filter(a => !a.isDeleted).length;
    setStatus('icsStatus', 'success', 'Found ' + total + ' event' + (total !== 1 ? 's' : ''));
  } catch (err) {
    setStatus('icsStatus', 'error', err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Get Schedule';
  }
}

function downloadICS() {
  if (!lastICS) return;
  const blob = new Blob([lastICS], { type: 'text/calendar;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'xlri_schedule.ics';
  a.click();
  URL.revokeObjectURL(a.href);
}

// ========== TIMETABLE VIEW ==========

function toLocalDateStr(d) {
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

function parseLocalDate(str) {
  const [y, m, day] = str.split('-').map(Number);
  return new Date(y, m - 1, day);
}

function getWeekRange(date) {
  const d = typeof date === 'string' ? parseLocalDate(date) : new Date(date);
  const day = d.getDay();
  d.setDate(d.getDate() - (day === 0 ? 6 : day - 1));
  const mon = new Date(d);
  const sun = new Date(d);
  sun.setDate(mon.getDate() + 6);
  return {
    start: toLocalDateStr(mon),
    end: toLocalDateStr(sun),
    days: ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map((name, i) => {
      const dd = new Date(mon);
      dd.setDate(mon.getDate() + i);
      return { name, date: toLocalDateStr(dd), dayNum: dd.getDate(), month: dd.toLocaleString('en',{month:'short'}) };
    }),
  };
}

function renderTimetable(sessions, activities) {
  const all = [
    ...sessions.filter(s => !s.isCancelled).map(s => ({ ...s, _kind: 'class', _id: s.sessionId, _code: s.course.courseCode, _name: s.course.courseName, _date: s.classDate })),
    ...activities.filter(a => !a.isDeleted).map(a => ({ ...a, _kind: 'activity', _id: a.id, _code: 'Activity', _name: a.name, _date: a.date })),
  ];

  if (!all.length) {
    document.getElementById('ttGrid').innerHTML = '<p style="text-align:center;padding:40px;color:#94a3b8">No events this week</p>';
    document.getElementById('ttLegend').classList.add('hidden');
    return;
  }

  all.sort((a, b) => a._date.localeCompare(b._date) || a.startTime.localeCompare(b.startTime));

  let minMin = 1440, maxMin = 0;
  for (const e of all) {
    const s = timeToMinutes(e.startTime);
    const en = timeToMinutes(e.endTime);
    if (s < minMin) minMin = s;
    if (en > maxMin) maxMin = en;
  }
  minMin = Math.floor(minMin / 30) * 30;
  maxMin = Math.ceil(maxMin / 30) * 30;

  const SLOT = 30;
  const slots = [];
  for (let m = minMin; m < maxMin; m += SLOT) {
    const h = Math.floor(m / 60);
    const min = m % 60;
    slots.push({ label: (h % 12 || 12) + ':' + (min ? '30' : '00') + (h < 12 ? 'am' : 'pm'), minutes: m });
  }

  const dateToCol = {};
  const week = getWeekRange(document.getElementById('ttDate').value);
  week.days.forEach((d, i) => { dateToCol[d.date] = i + 2; });

  const GRID_ROWS = 1 + slots.length;
  let gridCSS = 'grid-template-columns:55px repeat(7,1fr);grid-template-rows:auto repeat(' + slots.length + ',28px)';

  let cells = '<div class="timetable-header"><div style="text-align:right;padding-right:8px;font-size:11px;color:#94a3b8">Time</div>';
  for (const d of week.days) {
    cells += '<div>' + d.name + '<br><span style="font-weight:400;color:#94a3b8">' + d.month + ' ' + d.dayNum + '</span></div>';
  }
  cells += '</div>';

  for (let i = 0; i < slots.length; i++) {
    const row = i + 2;
    cells += '<div class="timetable-time" style="grid-row:' + row + '/span 1;grid-column:1">' + slots[i].label + '</div>';
  }

  const codeColors = {};
  const seenCodes = new Set();
  for (const e of all) {
    const code = e._code;
    if (!seenCodes.has(code)) {
      seenCodes.add(code);
      if (!codeColors[code]) codeColors[code] = getCourseColor(code);
    }
  }

  for (const e of all) {
    const col = dateToCol[e._date];
    if (!col) continue;
    const startM = timeToMinutes(e.startTime);
    const endM = timeToMinutes(e.endTime);
    const startRow = 2 + Math.round((startM - minMin) / SLOT);
    const endRow = 2 + Math.round((endM - minMin) / SLOT);
    const palette = e._kind === 'class' ? codeColors[e._code] || getCourseColor(e._code) : { bg: '#e8e8e8', border: '#1a1a1a', text: '#1a1a1a' };
    const rows = endRow - startRow;
    const venueName = e.venue ? e.venue.name : '';
    let html = '';
    if (rows >= 2) {
      html = '<div class="session-block" style="grid-row:' + startRow + '/' + endRow + ';grid-column:' + col + ';background:' + palette.bg + ';border-color:' + palette.border + ';color:' + palette.text + '">' +
        '<div class="course-code">' + (e._kind === 'class' ? e._code : 'Activity') + '</div>' +
        '<div class="course-name">' + e._name + '</div>' +
        (venueName ? '<div class="session-venue">' + venueName + '</div>' : '') +
        '</div>';
    } else {
      html = '<div class="session-block" style="grid-row:' + startRow + ';grid-column:' + col + ';background:' + palette.bg + ';border-color:' + palette.border + ';color:' + palette.text + ';font-size:10px">' +
        '<div class="course-code">' + (e._kind === 'class' ? e._code : 'Activity') + '</div>' +
        '<div class="course-name">' + e._name + '</div>' +
        '</div>';
    }
    cells += html;
  }

  document.getElementById('ttGrid').innerHTML = '<div class="timetable-grid" style="' + gridCSS + '">' + cells + '</div>';

  const legendItems = [];
  for (const code of seenCodes) {
    const c = codeColors[code];
    legendItems.push('<div class="legend-item"><div class="legend-swatch" style="background:' + c.bg + ';border-color:' + c.border + '"></div>' + code + '</div>');
  }
  document.getElementById('ttLegend').innerHTML = legendItems.join('');
  document.getElementById('ttLegend').classList.remove('hidden');
  document.getElementById('downloadPngBtn').style.display = '';
}

async function downloadTimetablePNG() {
  const btn = document.getElementById('downloadPngBtn');
  btn.disabled = true;
  btn.textContent = 'Rendering...';
  try {
    const el = document.getElementById('ttCard');
    const canvas = await html2canvas(el, {
      backgroundColor: '#ffffff',
      scale: 2,
      useCORS: true,
      logging: false,
    });
    const link = document.createElement('a');
    link.download = 'timetable.png';
    link.href = canvas.toDataURL('image/png');
    link.click();
  } finally {
    btn.disabled = false;
    btn.textContent = 'Download PNG';
  }
}

async function fetchTimetable() {
  const email = document.getElementById('ttEmail').value.trim();
  const password = document.getElementById('ttPassword').value;
  const dateVal = document.getElementById('ttDate').value;
  if (!email || !password) { setStatus('ttStatus', 'error', 'Please enter email and password'); return; }
  if (!dateVal) { setStatus('ttStatus', 'error', 'Please select a date'); return; }

  const week = getWeekRange(dateVal);
  const mode = 'all';

  const btn = document.getElementById('ttBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Loading...';
  try {
    const res = await fetch('/api/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, startDate: week.start, endDate: week.end, mode }),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || 'Request failed');
    renderTimetable(data.sessions || [], data.activities || []);
    document.getElementById('ttResults').classList.remove('hidden');
    document.getElementById('ttTitle').textContent = 'Weekly Timetable';
    document.getElementById('ttSubtitle').textContent = week.days[0].month + ' ' + week.days[0].dayNum + ' – ' + week.days[6].month + ' ' + week.days[6].dayNum + ' (' + week.start + ' – ' + week.end + ')';
    setStatus('ttStatus', 'success', '');
  } catch (err) {
    setStatus('ttStatus', 'error', err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Get Timetable';
  }
}

setDefaultDates();
</script>
</body>
</html>`;
  serveStatic(res, 200, 'text/html; charset=utf-8', html);
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');

  if (url.pathname.startsWith('/api/')) {
    handleAPI(req, res);
  } else {
    serveIndex(res);
  }
});

const PORT = process.env.PORT || 3001;
server.listen(PORT, () => {
  console.log(`Server running at http://localhost:${PORT}`);
});
