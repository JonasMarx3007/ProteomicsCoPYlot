export type SaveStateFileHandle = {
  name?: string;
  createWritable: () => Promise<{
    write: (data: Blob) => Promise<void>;
    close: () => Promise<void>;
    abort: () => Promise<void>;
  }>;
  getFile?: () => Promise<File>;
};

type FilePickerAcceptType = {
  description?: string;
  accept: Record<string, string[]>;
};

type SaveFilePickerOptions = {
  suggestedName?: string;
  types?: FilePickerAcceptType[];
  excludeAcceptAllOption?: boolean;
};

type OpenFilePickerOptions = {
  multiple?: boolean;
  types?: FilePickerAcceptType[];
  excludeAcceptAllOption?: boolean;
};

type PickerGlobal = typeof globalThis & {
  showSaveFilePicker?: (options?: SaveFilePickerOptions) => Promise<SaveStateFileHandle>;
  showOpenFilePicker?: (options?: OpenFilePickerOptions) => Promise<SaveStateFileHandle[]>;
  indexedDB?: IDBFactory;
};

type PersistedSaveStateTarget = {
  handle: SaveStateFileHandle;
  fileName: string | null;
};

const SAVE_STATE_TYPES: FilePickerAcceptType[] = [
  {
    description: "CoPYlot Save State",
    accept: {
      "application/octet-stream": [".copylotstate"],
      "application/json": [".json", ".gz", ".bin"],
    },
  },
];

const SAVE_STATE_DB_NAME = "copylot-save-state";
const SAVE_STATE_STORE_NAME = "handles";
const SAVE_STATE_RECORD_KEY = "current-save-state";

function pickerGlobal(): PickerGlobal {
  return globalThis as PickerGlobal;
}

function normalizeFileName(fileName: string | null | undefined): string {
  const trimmed = String(fileName ?? "").trim();
  if (!trimmed) return "copylot_state.copylotstate";
  return trimmed.toLowerCase().endsWith(".copylotstate")
    ? trimmed
    : `${trimmed}.copylotstate`;
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function openDatabase(): Promise<IDBDatabase | null> {
  const idb = pickerGlobal().indexedDB;
  if (!idb) return Promise.resolve(null);
  return new Promise((resolve, reject) => {
    const request = idb.open(SAVE_STATE_DB_NAME, 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(SAVE_STATE_STORE_NAME)) {
        db.createObjectStore(SAVE_STATE_STORE_NAME);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function withStore<T>(
  mode: IDBTransactionMode,
  work: (store: IDBObjectStore) => Promise<T> | T
): Promise<T | null> {
  const db = await openDatabase();
  if (!db) return null;
  try {
    return await new Promise<T>((resolve, reject) => {
      const transaction = db.transaction(SAVE_STATE_STORE_NAME, mode);
      const store = transaction.objectStore(SAVE_STATE_STORE_NAME);
      let settled = false;
      let resultValue!: T;

      Promise.resolve(work(store))
        .then((value) => {
          resultValue = value;
        })
        .catch((error) => {
          settled = true;
          reject(error);
        });

      transaction.oncomplete = () => {
        if (settled) return;
        settled = true;
        resolve(resultValue);
      };
      transaction.onerror = () => {
        if (settled) return;
        settled = true;
        reject(transaction.error);
      };
      transaction.onabort = () => {
        if (settled) return;
        settled = true;
        reject(transaction.error);
      };
    });
  } finally {
    db.close();
  }
}

export function supportsNativeOpenStatePicker(): boolean {
  return typeof pickerGlobal().showOpenFilePicker === "function";
}

export function isPickerAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export async function persistSaveStateTarget(
  handle: SaveStateFileHandle | null
): Promise<void> {
  if (!handle) {
    await clearPersistedSaveStateTarget();
    return;
  }
  await withStore("readwrite", (store) => {
    store.put(
      {
        handle,
        fileName: typeof handle.name === "string" ? handle.name : null,
      } satisfies PersistedSaveStateTarget,
      SAVE_STATE_RECORD_KEY
    );
  }).catch(() => null);
}

export async function loadPersistedSaveStateTarget(): Promise<{
  handle: SaveStateFileHandle | null;
  fileName: string | null;
}> {
  const result = await withStore("readonly", (store) => {
    return new Promise<PersistedSaveStateTarget | null>((resolve, reject) => {
      const request = store.get(SAVE_STATE_RECORD_KEY);
      request.onsuccess = () => {
        const value = request.result;
        if (!value || typeof value !== "object") {
          resolve(null);
          return;
        }
        resolve(value as PersistedSaveStateTarget);
      };
      request.onerror = () => reject(request.error);
    });
  }).catch(() => null);
  return {
    handle: result?.handle ?? null,
    fileName: result?.fileName ?? null,
  };
}

export async function clearPersistedSaveStateTarget(): Promise<void> {
  await withStore("readwrite", (store) => {
    store.delete(SAVE_STATE_RECORD_KEY);
  }).catch(() => null);
}

export async function openRestoreStateFileWithPicker(): Promise<{
  file: File;
  handle: SaveStateFileHandle | null;
}> {
  const openPicker = pickerGlobal().showOpenFilePicker;
  if (typeof openPicker !== "function") {
    throw new Error("Native open-file picker is not available in this browser.");
  }
  const [handle] = await openPicker({
    multiple: false,
    types: SAVE_STATE_TYPES,
    excludeAcceptAllOption: false,
  });
  if (!handle || typeof handle.getFile !== "function") {
    throw new Error("Selected save state file could not be opened.");
  }
  const file = await handle.getFile();
  return { file, handle };
}

async function writeBlobToHandle(handle: SaveStateFileHandle, blob: Blob): Promise<void> {
  const writable = await handle.createWritable();
  try {
    await writable.write(blob);
    await writable.close();
  } catch (error) {
    // Never commit a partial write. Preserve the original failure if cleanup fails.
    await writable.abort().catch(() => undefined);
    throw error;
  }
}

export async function saveRestoreStateBlob(options: {
  blob: Blob;
  suggestedName?: string | null;
  existingHandle?: SaveStateFileHandle | null;
  forcePicker?: boolean;
}): Promise<{
  fileName: string;
  handle: SaveStateFileHandle | null;
  method: "handle" | "download";
}> {
  const { blob, suggestedName, existingHandle = null, forcePicker = false } = options;
  const normalizedName = normalizeFileName(suggestedName);

  if (!forcePicker && existingHandle) {
    await writeBlobToHandle(existingHandle, blob);
    return {
      fileName: existingHandle.name?.trim() || normalizedName,
      handle: existingHandle,
      method: "handle",
    };
  }

  const savePicker = pickerGlobal().showSaveFilePicker;
  if (typeof savePicker === "function") {
    const handle = await savePicker({
      suggestedName: normalizedName,
      types: SAVE_STATE_TYPES,
      excludeAcceptAllOption: false,
    });
    await writeBlobToHandle(handle, blob);
    return {
      fileName: handle.name?.trim() || normalizedName,
      handle,
      method: "handle",
    };
  }

  triggerDownload(blob, normalizedName);
  return {
    fileName: normalizedName,
    handle: null,
    method: "download",
  };
}
