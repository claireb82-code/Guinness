// Venue websites are user-submitted. Only ever link to http(s) URLs: escaping alone does not stop a
// "javascript:" href. Mirrored by safeHttpUrl() in public/standalone.html (tests keep the two in sync).
export function safeHttpUrl(value) {
  if (typeof value !== 'string') return '';
  const raw = value.trim();
  if (!raw) return '';
  try {
    const u = new URL(/^[a-z][a-z0-9+.-]*:/i.test(raw) ? raw : 'https://' + raw);
    return u.protocol === 'http:' || u.protocol === 'https:' ? u.href : '';
  } catch {
    return '';
  }
}
