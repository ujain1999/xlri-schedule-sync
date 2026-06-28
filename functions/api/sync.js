import { login, fetchSchedule, fetchClassActivities, generateICS } from '../_utils/xlri';

export async function onRequest(context) {
  const { request } = context;
  if (request.method !== 'OPTIONS' && request.method !== 'POST') {
    return new Response('Method not allowed', { status: 405 });
  }

  const headers = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Content-Type': 'application/json',
  };

  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers });
  }

  try {
    const { email, password, startDate, endDate, mode } = await request.json();
    if (!email || !password) {
      return new Response(JSON.stringify({ error: 'Email and password required' }), { status: 400, headers });
    }

    const loginData = await login(email, password);
    let sessions = [];
    let activities = [];

    if (mode === 'classes' || mode === 'all' || !mode) {
      sessions = await fetchSchedule(loginData.token, startDate, endDate);
    }
    if (mode === 'activities' || mode === 'all' || !mode) {
      activities = await fetchClassActivities(loginData.token, startDate, endDate);
    }

    const ics = generateICS(sessions, activities);
    return new Response(JSON.stringify({ success: true, sessions, activities, ics }), { headers });
  } catch (err) {
    return new Response(JSON.stringify({ error: err.message }), { status: 500, headers });
  }
}
