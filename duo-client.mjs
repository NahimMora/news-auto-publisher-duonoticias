#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { basename } from 'node:path';

const BASE_URL = process.env.DUO_BASE_URL || 'http://localhost:3000';
const ADMIN_KEY = process.env.DUO_ADMIN_KEY;

if (!ADMIN_KEY) {
  console.error('Missing DUO_ADMIN_KEY in environment.');
  process.exit(1);
}

const args = process.argv.slice(2);
const fileFlagIndex = args.indexOf('--file');
if (fileFlagIndex === -1 || !args[fileFlagIndex + 1]) {
  console.error('Usage: node duo-client.mjs --file <path-to-json>');
  process.exit(1);
}

const inputPath = args[fileFlagIndex + 1];
const raw = readFileSync(inputPath, 'utf8');
const parsed = JSON.parse(raw);
const items = Array.isArray(parsed) ? parsed : (Array.isArray(parsed.items) ? parsed.items : [parsed]);

async function apiFetch(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      'x-admin-key': ADMIN_KEY,
      ...(options.headers || {}),
    },
  });
  const json = await res.json().catch(() => null);
  if (!res.ok) {
    const errorMessage = json?.error ? JSON.stringify(json.error) : res.statusText;
    throw new Error(`${res.status} ${errorMessage}`);
  }
  return json;
}

async function createMediaFromUrl(url, alt) {
  const payload = {
    url,
    alt: alt || null,
  };
  const result = await apiFetch('/api/admin/media', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return result?.data?.id;
}

async function uploadLocalImage(filePath, alt) {
  const buffer = readFileSync(filePath);
  const form = new FormData();
  const blob = new Blob([buffer]);
  form.append('file', blob, basename(filePath));
  if (alt) form.append('alt', alt);
  const result = await apiFetch('/api/admin/media/upload', {
    method: 'POST',
    body: form,
  });
  return result?.data?.id;
}

async function normalizeItem(item) {
  const normalized = { ...item };

  if (!normalized.coverImageId) {
    if (normalized.imageUrl) {
      normalized.coverImageId = await createMediaFromUrl(normalized.imageUrl, normalized.title);
    } else if (normalized.imagePath) {
      normalized.coverImageId = await uploadLocalImage(normalized.imagePath, normalized.title);
    }
  }

  delete normalized.imageUrl;
  delete normalized.imagePath;
  return normalized;
}

async function run() {
  const normalizedItems = [];
  for (const item of items) {
    normalizedItems.push(await normalizeItem(item));
  }

  if (normalizedItems.length === 1) {
    const result = await apiFetch('/api/admin/articles', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(normalizedItems[0]),
    });
    console.log('Created:', result);
    return;
  }

  const result = await apiFetch('/api/admin/articles/bulk', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items: normalizedItems }),
  });
  console.log('Bulk created:', result);
}

run().catch((err) => {
  console.error('Error:', err.message);
  process.exit(1);
});
