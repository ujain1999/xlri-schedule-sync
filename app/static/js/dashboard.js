async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Request failed');
  return data;
}

async function putJSON(url, body) {
  const res = await fetch(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Request failed');
  return data;
}

function setStatus(id, type, msg) {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = 'status ' + type;
  el.textContent = msg;
}

const xlriForm = document.getElementById('xlriForm');
if (xlriForm) {
  xlriForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('xlriEmail').value.trim();
    const password = document.getElementById('xlriPassword').value;
    setStatus('xlriStatus', 'info', 'Verifying...');
    try {
      await postJSON('/api/xlri/credentials', { email, password });
      setStatus('xlriStatus', 'success', 'Connected. Reloading...');
      setTimeout(() => location.reload(), 800);
    } catch (err) {
      setStatus('xlriStatus', 'error', err.message);
    }
  });
}

const xlriDisconnect = document.getElementById('xlriDisconnect');
if (xlriDisconnect) {
  xlriDisconnect.addEventListener('click', async () => {
    if (!confirm('Disconnect your XLRI ERP credentials? Sync will pause until reconnected.')) return;
    await fetch('/api/xlri/credentials', { method: 'DELETE' });
    location.reload();
  });
}

const settingsForm = document.getElementById('settingsForm');
if (settingsForm) {
  settingsForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = {
      enabled: document.getElementById('syncEnabled').checked,
      window_weeks_ahead: parseInt(document.getElementById('windowWeeksAhead').value, 10),
      window_days_behind: parseInt(document.getElementById('windowDaysBehind').value, 10),
    };
    setStatus('settingsStatus', 'info', 'Saving...');
    try {
      await putJSON('/api/sync/settings', body);
      setStatus('settingsStatus', 'success', 'Saved');
    } catch (err) {
      setStatus('settingsStatus', 'error', err.message);
    }
  });
}

const syncNowBtn = document.getElementById('syncNowBtn');
if (syncNowBtn) {
  syncNowBtn.addEventListener('click', async () => {
    syncNowBtn.disabled = true;
    setStatus('syncNowStatus', 'info', 'Sync started...');
    try {
      await postJSON('/api/sync/now');
      pollSyncStatus();
    } catch (err) {
      setStatus('syncNowStatus', 'error', err.message);
      syncNowBtn.disabled = false;
    }
  });
}

async function pollSyncStatus() {
  for (let i = 0; i < 30; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    const res = await fetch('/api/sync/runs?limit=1');
    const runs = await res.json();
    const latest = runs[0];
    if (latest && latest.status !== 'running') {
      const summary = `${latest.status} -- created ${latest.events_created}, updated ${latest.events_updated}, deleted ${latest.events_deleted}` +
        (latest.error_message ? `: ${latest.error_message}` : '');
      setStatus('syncNowStatus', latest.status === 'success' ? 'success' : 'error', summary);
      if (syncNowBtn) syncNowBtn.disabled = false;
      setTimeout(() => location.reload(), 1500);
      return;
    }
  }
  setStatus('syncNowStatus', 'error', 'Sync is taking longer than expected');
  if (syncNowBtn) syncNowBtn.disabled = false;
}
