const API_URL = import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL || 'http://localhost:8000';

export function getAdminToken() {
  return localStorage.getItem('admin_token') || '';
}

export function setAdminToken(token) {
  if (token) localStorage.setItem('admin_token', token);
  else localStorage.removeItem('admin_token');
}

export function getClientToken() {
  return localStorage.getItem('client_token') || '';
}

export function setClientToken(token) {
  if (token) localStorage.setItem('client_token', token);
  else localStorage.removeItem('client_token');
}

export async function api(path, options = {}) {
  const token = getAdminToken();
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token && (path.startsWith('/api/admin') || path.startsWith('/api/integrations') || path.startsWith('/api/auth/me') || path.startsWith('/api/auth/change-password'))) {
    headers.Authorization = `Bearer ${token}`;
  }
  const clientToken = getClientToken();
  if (clientToken && path.startsWith('/api/auth/client/')) {
    headers.Authorization = `Bearer ${clientToken}`;
  }
  const res = await fetch(`${API_URL}${path}`, { headers, ...options });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export const loginAdmin = (payload) => api('/api/auth/login', { method: 'POST', body: JSON.stringify(payload) });
export const adminMe = () => api('/api/auth/me');
export const changeAdminPassword = (payload) => api('/api/auth/change-password', { method: 'POST', body: JSON.stringify(payload) });
export const logoutAdmin = () => setAdminToken('');

export const getProducts = () => api('/api/products');
export const getServices = () => api('/api/services');
export const getChatSettings = () => api('/api/settings/chat');
export const sendChat = (payload) => api('/api/chat', { method: 'POST', body: JSON.stringify(payload) });

export const adminList = (table) => api(`/api/admin/${table}`);
export const adminCreate = (table, payload) => api(`/api/admin/${table}`, { method: 'POST', body: JSON.stringify(payload) });
export const adminUpdate = (table, id, payload) => api(`/api/admin/${table}/${id}`, { method: 'PATCH', body: JSON.stringify(payload) });
export const adminDelete = (table, id) => api(`/api/admin/${table}/${id}`, { method: 'DELETE' });
export const testHuggingFace = (payload) => api('/api/admin/test-huggingface', { method: 'POST', body: JSON.stringify(payload) });
export const exportLeadsCsv = () => api('/api/admin/leads/export.csv');
export const syncDriveWidget = (id) => api(`/api/integrations/drive/sync/${id}`, { method: 'POST' });
export const addManualKnowledge = (payload) => api('/api/integrations/knowledge/manual', { method: 'POST', body: JSON.stringify(payload) });

export const registerClient = (payload) => api('/api/auth/client/register', { method: 'POST', body: JSON.stringify(payload) });
export const loginClient = (payload) => api('/api/auth/client/login', { method: 'POST', body: JSON.stringify(payload) });
export const clientMe = () => api('/api/auth/client/me');
export const changeClientPassword = (payload) => api('/api/auth/client/change-password', { method: 'POST', body: JSON.stringify(payload) });
export const logoutClient = () => setClientToken('');
