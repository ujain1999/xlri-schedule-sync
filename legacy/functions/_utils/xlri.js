const BASE_URL = 'https://xlerp.xlri.ac.in';

export async function login(email, password) {
  const res = await fetch(`${BASE_URL}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  const data = await res.json();
  if (!data.success) throw new Error(data.message || 'Login failed');
  return data.data;
}

export async function fetchSchedule(token, startDate, endDate) {
  const url = `${BASE_URL}/api/v1/schedule/my-schedule/student?startDate=${startDate}&endDate=${endDate}`;
  const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  const data = await res.json();
  if (!data.success) throw new Error(data.message || 'Failed to fetch schedule');
  return data.data;
}

export async function fetchClassActivities(token, startDate, endDate) {
  const url = `${BASE_URL}/api/v1/class-activities/my?startDate=${startDate}&endDate=${endDate}`;
  const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  const data = await res.json();
  if (!data.success) throw new Error(data.message || 'Failed to fetch class activities');
  return data.data;
}

export function generateICS(sessions, activities) {
  function formatICSDate(date, time) {
    return date.replace(/-/g, '') + 'T' + time.replace(/:/g, '') + '00';
  }
  function escapeICS(text) {
    if (!text) return '';
    return String(text).replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\n/g, '\\n');
  }

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
