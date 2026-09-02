const API_URL =
  import.meta.env.VITE_API_BASE_URL ||
  import.meta.env.VITE_API_URL ||
  'http://localhost:8000';

function cleanBaseUrl(url) {
  return String(url || '').trim().replace(/\/$/, '');
}

const BASE_URL = cleanBaseUrl(API_URL);

export function getAdminToken() {
  return (
    localStorage.getItem('admin_token') ||
    localStorage.getItem('adminToken') ||
    localStorage.getItem('token') ||
    sessionStorage.getItem('admin_token') ||
    sessionStorage.getItem('adminToken') ||
    sessionStorage.getItem('token') ||
    ''
  );
}

export function setAdminToken(token) {
  if (token) {
    localStorage.setItem('admin_token', token);
    localStorage.setItem('adminToken', token);
  } else {
    localStorage.removeItem('admin_token');
    localStorage.removeItem('adminToken');
    localStorage.removeItem('token');
    sessionStorage.removeItem('admin_token');
    sessionStorage.removeItem('adminToken');
    sessionStorage.removeItem('token');
  }
}

export function getClientToken() {
  return (
    localStorage.getItem('client_token') ||
    localStorage.getItem('clientToken') ||
    sessionStorage.getItem('client_token') ||
    sessionStorage.getItem('clientToken') ||
    ''
  );
}

export function setClientToken(token) {
  if (token) {
    localStorage.setItem('client_token', token);
    localStorage.setItem('clientToken', token);
  } else {
    localStorage.removeItem('client_token');
    localStorage.removeItem('clientToken');
    sessionStorage.removeItem('client_token');
    sessionStorage.removeItem('clientToken');
  }
}

function isAdminRoute(path) {
  return (
    path.startsWith('/api/admin') ||
    path.startsWith('/api/integrations') ||
    path.startsWith('/api/auth/me') ||
    path.startsWith('/api/auth/change-password') ||
    path.startsWith('/api/chat/admin')
  );
}

function isClientRoute(path) {
  return (
    path.startsWith('/api/auth/client/') ||
    path.startsWith('/api/chat/client')
  );
}

async function parseErrorResponse(res) {
  let message = '';

  try {
    const text = await res.text();

    if (!text) {
      return `Request failed with status ${res.status}`;
    }

    try {
      const data = JSON.parse(text);
      message = data.detail || data.message || JSON.stringify(data);
    } catch {
      message = text;
    }
  } catch {
    message = `Request failed with status ${res.status}`;
  }

  return message || `Request failed with status ${res.status}`;
}

export async function api(path, options = {}) {
  const adminToken = getAdminToken();
  const clientToken = getClientToken();

  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  if (adminToken && isAdminRoute(path)) {
    headers.Authorization = `Bearer ${adminToken}`;
  }

  if (clientToken && isClientRoute(path)) {
    headers.Authorization = `Bearer ${clientToken}`;
  }

  let res;

  try {
    res = await fetch(`${BASE_URL}${path}`, {
      ...options,
      headers,
    });
  } catch (error) {
    throw new Error(
      `Failed to fetch. Please check that the backend is running, Render is awake, and VITE_API_BASE_URL is correct. Current API URL: ${BASE_URL}`
    );
  }

  if (!res.ok) {
    throw new Error(await parseErrorResponse(res));
  }

  if (res.status === 204) {
    return null;
  }

  const text = await res.text();

  if (!text) {
    return null;
  }

  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

// Admin auth
export const loginAdmin = (payload) =>
  api('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const adminMe = () =>
  api('/api/auth/me');

export const changeAdminPassword = (payload) =>
  api('/api/auth/change-password', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const logoutAdmin = () =>
  setAdminToken('');

// Public frontend data
export const getProducts = () =>
  api('/api/products');

export const getServices = () =>
  api('/api/services');

export const getChatSettings = () =>
  api('/api/settings/chat');

export const sendChat = (payload) => {
  const adminToken = getAdminToken();
  const clientToken = getClientToken();

  if (adminToken) {
    return api('/api/chat/admin', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  if (clientToken) {
    return api('/api/chat/client', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  return api('/api/chat', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
};

// Admin CRUD
export const adminList = (table) =>
  api(`/api/admin/${table}`);

export const adminCreate = (table, payload) =>
  api(`/api/admin/${table}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const adminUpdate = (table, id, payload) =>
  api(`/api/admin/${table}/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });

export const adminDelete = (table, id) =>
  api(`/api/admin/${table}/${id}`, {
    method: 'DELETE',
  });

// Admin AI
export const testHuggingFace = (payload) =>
  api('/api/admin/test-huggingface', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

// Leads
export const exportLeadsCsv = () =>
  api('/api/admin/leads/export.csv');

// Google Drive integrations
export const syncDriveWidget = (id) =>
  api(`/api/integrations/drive/sync/${id}`, {
    method: 'POST',
  });

export const listDriveFolders = (id) =>
  api(`/api/integrations/drive/folders/${id}`, {
    method: 'GET',
  });

// Knowledge base
export const addManualKnowledge = (payload) =>
  api('/api/integrations/knowledge/manual', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

// Client auth
export const registerClient = (payload) =>
  api('/api/auth/client/register', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const loginClient = (payload) =>
  api('/api/auth/client/login', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const clientMe = () =>
  api('/api/auth/client/me');

export const changeClientPassword = (payload) =>
  api('/api/auth/client/change-password', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const logoutClient = () =>
  setClientToken('');
