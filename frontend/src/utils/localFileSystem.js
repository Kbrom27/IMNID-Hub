/**
 * Local File System Access Helper
 * Enables web pages to save exported files directly to user-selected local folders
 * using the modern HTML5 File System Access API (showDirectoryPicker / showSaveFilePicker)
 * instead of dumping everything into the default ~/Downloads directory.
 */
import { useState, useEffect } from 'react';

let storedHandle = null;
let storedFolderName = '';
const listeners = new Set();

const DB_NAME = 'imnid_fs_store';
const STORE_NAME = 'handles';
const KEY = 'active_dir';

function openDb() {
  return new Promise((resolve) => {
    if (typeof window === 'undefined' || !window.indexedDB) {
      resolve(null);
      return;
    }
    try {
      const req = window.indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = (e) => {
        const db = e.target.result;
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          db.createObjectStore(STORE_NAME);
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
}

async function idbGet() {
  try {
    const db = await openDb();
    if (!db) return null;
    return new Promise((resolve) => {
      const tx = db.transaction(STORE_NAME, 'readonly');
      const store = tx.objectStore(STORE_NAME);
      const req = store.get(KEY);
      req.onsuccess = () => resolve(req.result || null);
      req.onerror = () => resolve(null);
    });
  } catch {
    return null;
  }
}

async function idbSet(val) {
  try {
    const db = await openDb();
    if (!db) return;
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    if (val) {
      store.put(val, KEY);
    } else {
      store.delete(KEY);
    }
  } catch (err) {
    console.warn('Failed to store handle in idb', err);
  }
}

function notifyListeners() {
  const current = getStoredDirectoryHandle();
  listeners.forEach((fn) => {
    try {
      fn(current);
    } catch (e) {
      console.error(e);
    }
  });
}

// Restore handle from IndexedDB on startup
if (typeof window !== 'undefined') {
  idbGet().then((saved) => {
    if (saved && saved.handle) {
      storedHandle = saved.handle;
      storedFolderName = saved.name || saved.handle.name || '';
      notifyListeners();
    }
  });
}

/**
 * Subscribe to stored directory handle changes
 */
export function subscribeDirectoryHandle(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/**
 * React hook to reactively track active local directory handle
 */
export function useStoredDirectoryHandle() {
  const [handleInfo, setHandleInfo] = useState(() => getStoredDirectoryHandle());

  useEffect(() => {
    setHandleInfo(getStoredDirectoryHandle());
    return subscribeDirectoryHandle((val) => setHandleInfo(val));
  }, []);

  return handleInfo;
}

/**
 * Store active directory handle when user selects a local folder
 */
export function setStoredDirectoryHandle(handle, folderName = '') {
  storedHandle = handle;
  storedFolderName = folderName || (handle ? handle.name : '');
  if (handle) {
    idbSet({ handle, name: storedFolderName });
  } else {
    idbSet(null);
  }
  notifyListeners();
}

/**
 * Retrieve active directory handle
 */
export function getStoredDirectoryHandle() {
  if (!storedHandle) return null;
  return {
    handle: storedHandle,
    name: storedFolderName || storedHandle.name || 'Selected Folder',
  };
}

/**
 * Clear stored directory handle
 */
export function clearStoredDirectoryHandle() {
  storedHandle = null;
  storedFolderName = '';
  idbSet(null);
  notifyListeners();
}

/**
 * Verify and request readwrite permission on FileSystemHandle
 */
export async function verifyDirectoryPermission(dirHandle, readWrite = true) {
  if (!dirHandle) return false;
  const options = {};
  if (readWrite) options.mode = 'readwrite';
  try {
    if (typeof dirHandle.queryPermission === 'function') {
      const state = await dirHandle.queryPermission(options);
      if (state === 'granted') return true;
    }
    if (typeof dirHandle.requestPermission === 'function') {
      try {
        const state = await dirHandle.requestPermission(options);
        return state === 'granted';
      } catch (permErr) {
        console.warn('Permission request without user gesture failed:', permErr);
        return false;
      }
    }
  } catch (err) {
    console.warn('Permission query/request error:', err);
    return false;
  }
  return true;
}

/**
 * Save a Blob directly into a FileSystemDirectoryHandle
 */
export async function saveBlobToDirectory(dirHandle, fileName, blob) {
  if (!dirHandle || typeof dirHandle.getFileHandle !== 'function') {
    throw new Error('Invalid directory handle');
  }
  const granted = await verifyDirectoryPermission(dirHandle, true);
  if (!granted) {
    throw new Error('Permission to write to the chosen directory was not granted by the browser.');
  }
  const fileHandle = await dirHandle.getFileHandle(fileName, { create: true });
  const writable = await fileHandle.createWritable();
  await writable.write(blob);
  await writable.close();
  return fileHandle;
}

/**
 * Prompt user to select destination file location using native OS Save As dialog
 */
export async function saveBlobWithPicker(fileName, blob) {
  if (typeof window === 'undefined' || !('showSaveFilePicker' in window)) {
    return null;
  }

  const ext = fileName.split('.').pop()?.toLowerCase() || '';
  const typeMap = {
    xlsx: {
      description: 'Excel Spreadsheet (*.xlsx)',
      accept: {
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      },
    },
    xls: {
      description: 'Excel Workbook (*.xls)',
      accept: { 'application/vnd.ms-excel': ['.xls'] },
    },
    csv: {
      description: 'CSV Document (*.csv)',
      accept: { 'text/csv': ['.csv'] },
    },
    json: {
      description: 'JSON Document (*.json)',
      accept: { 'application/json': ['.json'] },
    },
    zip: {
      description: 'ZIP Archive (*.zip)',
      accept: { 'application/zip': ['.zip'] },
    },
  };

  const types = typeMap[ext] ? [typeMap[ext]] : [];

  const fileHandle = await window.showSaveFilePicker({
    suggestedName: fileName,
    types: types.length > 0 ? types : undefined,
  });

  const writable = await fileHandle.createWritable();
  await writable.write(blob);
  await writable.close();
  return fileHandle;
}

/**
 * Standard browser download fallback
 */
export function triggerBrowserDownload(blob, fileName) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 100);
}
