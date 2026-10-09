/**
 * IndexedDB outbox for offline telemetry when Tailscale/VPN drops.
 */

import { openDB, type DBSchema, type IDBPDatabase } from 'idb';
import type { TelemetryPoint } from '../types/telemetry';

interface TelemetryDB extends DBSchema {
  outbox: {
    key: number;
    value: {
      id?: number;
      point: TelemetryPoint;
      queuedAt: number;
    };
  };
}

const DB_NAME = 'sovereign-overwatch-telemetry';
const STORE = 'outbox';

let dbPromise: Promise<IDBPDatabase<TelemetryDB>> | null = null;

function getDb() {
  if (!dbPromise) {
    dbPromise = openDB<TelemetryDB>(DB_NAME, 1, {
      upgrade(db) {
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true });
        }
      },
    });
  }
  return dbPromise;
}

export async function enqueuePoint(point: TelemetryPoint): Promise<void> {
  const db = await getDb();
  await db.add(STORE, { point, queuedAt: Date.now() });
}

export async function countQueued(): Promise<number> {
  const db = await getDb();
  return db.count(STORE);
}

export async function drainQueue(): Promise<TelemetryPoint[]> {
  const db = await getDb();
  const rows = await db.getAll(STORE);
  return rows.map((r) => r.point);
}

export async function clearQueue(): Promise<void> {
  const db = await getDb();
  await db.clear(STORE);
}

export async function deleteAllQueued(): Promise<void> {
  const db = await getDb();
  const keys = await db.getAllKeys(STORE);
  const tx = db.transaction(STORE, 'readwrite');
  await Promise.all(keys.map((k) => tx.store.delete(k)));
  await tx.done;
}
