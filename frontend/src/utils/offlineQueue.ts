// Offline Queue Manager for handling visit submissions when offline
import { openDB } from 'idb';

const DB_NAME = 'field-geocoder-offline';
const DB_VERSION = 2;

interface QueuedVisit {
  id?: number;
  accountId: string;
  agentId: string;
  timestamp: string;
  latitude: number;
  longitude: number;
  gpsAccuracy?: number;
  outcome: string;
  dwellTime?: number;
  remarks?: string;
  trajectory?: any[];
  queuedAt: number;
  retries: number;
  synced: boolean;
  lastError?: string;
  failedAt?: number;
}

class OfflineQueueManager {
  private db: any = null;
  private syncInProgress = false;

  async init() {
    if (this.db) return this.db;

    this.db = await openDB(DB_NAME, DB_VERSION, {
      upgrade(db) {
        if (!db.objectStoreNames.contains('offline-visits')) {
          const store = db.createObjectStore('offline-visits', {
            keyPath: 'id',
            autoIncrement: true,
          });
          store.createIndex('timestamp', 'timestamp');
          store.createIndex('synced', 'synced');
        }
        if (!db.objectStoreNames.contains('dead-letter-visits')) {
          const deadLetterStore = db.createObjectStore('dead-letter-visits', {
            keyPath: 'id',
          });
          deadLetterStore.createIndex('failedAt', 'failedAt');
        }
      },
    });

    return this.db;
  }

  async queueVisit(visitData: Omit<QueuedVisit, 'id' | 'queuedAt' | 'retries' | 'synced'>): Promise<number> {
    await this.init();
    
    const visit: QueuedVisit = {
      ...visitData,
      queuedAt: Date.now(),
      retries: 0,
      synced: false,
    };

    return this.db.add('offline-visits', visit);
  }

  async getPendingVisits(): Promise<QueuedVisit[]> {
    await this.init();

    const visits: QueuedVisit[] = await this.db.getAll('offline-visits');

    return visits.filter((visit) => visit.synced === false);
  }

  async getAllVisits(): Promise<QueuedVisit[]> {
    await this.init();
    return this.db.getAll('offline-visits');
  }

  async markSynced(id: number): Promise<void> {
    await this.init();
    const visit = await this.db.get('offline-visits', id);
    if (visit) {
      visit.synced = true;
      await this.db.put('offline-visits', visit);
    }
  }

  async incrementRetry(id: number): Promise<void> {
    await this.init();
    const visit = await this.db.get('offline-visits', id);
    if (visit) {
      visit.retries++;
      await this.db.put('offline-visits', visit);
    }
  }

  async removeVisit(id: number): Promise<void> {
    await this.init();
    await this.db.delete('offline-visits', id);
  }

  async syncAll(): Promise<{ synced: number; failed: number; deadLetter: number }> {
    if (this.syncInProgress) {
      console.log('Sync already in progress');
      return { synced: 0, failed: 0, deadLetter: 0 };
    }

    this.syncInProgress = true;
    let synced = 0;
    let failed = 0;
    let deadLetter = 0;

    try {
      const pendingVisits = await this.getPendingVisits();

      for (const visit of pendingVisits) {
        try {
          const response = await fetch('/api/visits', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...(localStorage.getItem('access_token')
                ? { Authorization: `Bearer ${localStorage.getItem('access_token')}` }
                : {}),
            },
            body: JSON.stringify({
              account_id: visit.accountId,
              agent_id: visit.agentId,
              timestamp: visit.timestamp,
              latitude: visit.latitude,
              longitude: visit.longitude,
              gps_accuracy: visit.gpsAccuracy,
              outcome: visit.outcome,
              dwell_time: visit.dwellTime,
              remarks: visit.remarks,
              trajectory: visit.trajectory,
            }),
          });

          if (response.ok) {
            await this.markSynced(visit.id!);
            synced++;
          } else {
            await this.incrementRetry(visit.id!);
            failed++;
            
            // Check if max retries exceeded
            const updatedVisit = await this.db.get('offline-visits', visit.id);
            if (updatedVisit && updatedVisit.retries >= 5) {
              updatedVisit.lastError = `HTTP ${response.status}`;
              updatedVisit.failedAt = Date.now();
              await this.db.put('dead-letter-visits', updatedVisit);
              await this.removeVisit(visit.id!);
              deadLetter++;
            }
          }
        } catch (error) {
          console.error('Failed to sync visit:', visit.id, error);
          await this.incrementRetry(visit.id!);
          failed++;
          const updatedVisit = await this.db.get('offline-visits', visit.id);
          if (updatedVisit && updatedVisit.retries >= 5) {
            updatedVisit.lastError = error instanceof Error ? error.message : 'Network error';
            updatedVisit.failedAt = Date.now();
            await this.db.put('dead-letter-visits', updatedVisit);
            await this.removeVisit(visit.id!);
            deadLetter++;
          }
        }
      }
    } finally {
      this.syncInProgress = false;
    }

    return { synced, failed, deadLetter };
  }

  async getStats(): Promise<{ pending: number; synced: number; deadLetter: number; total: number }> {
    await this.init();
    const allVisits = await this.getAllVisits();
    const pending = allVisits.filter(v => !v.synced).length;
    const synced = allVisits.filter(v => v.synced).length;
    const deadLetter = await this.db.count('dead-letter-visits');
    return { pending, synced, deadLetter, total: allVisits.length + deadLetter };
  }
}

export const offlineQueue = new OfflineQueueManager();

// Auto-sync when online
window.addEventListener('online', () => {
  console.log('Back online, syncing offline visits...');
  offlineQueue.syncAll().then(result => {
    console.log('Sync complete:', result);
  });
});

// Periodic sync
setInterval(() => {
  if (navigator.onLine) {
    offlineQueue.syncAll().then(result => {
      if (result.synced > 0 || result.failed > 0) {
        console.log('Periodic sync:', result);
      }
    });
  }
}, 5 * 60 * 1000); // Every 5 minutes

// Export for use in components
export type { QueuedVisit };