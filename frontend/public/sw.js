// Service Worker for Offline Support
const CACHE_NAME = 'field-geocoder-v2';
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/manifest.json',
];
const MAP_HOSTS = ['tile.openstreetmap.org', 'a.tile.openstreetmap.org', 'b.tile.openstreetmap.org', 'c.tile.openstreetmap.org'];

const OFFLINE_QUEUE_DB = 'offline-queue';
const OFFLINE_QUEUE_STORE = 'visits';

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Handle API requests with network-first strategy
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(handleApiRequest(event.request));
    return;
  }

  if (MAP_HOSTS.includes(url.hostname)) {
    event.respondWith(handleMapRequest(event.request));
    return;
  }

  // Handle static assets with cache-first strategy
  event.respondWith(handleStaticRequest(event.request));
});

async function handleApiRequest(request) {
  const cache = await caches.open(CACHE_NAME);

  try {
    // Network first - try to fetch from network
    const networkResponse = await fetch(request.clone());

    if (networkResponse.ok) {
      // Cache successful GET requests
      if (request.method === 'GET') {
        cache.put(request, networkResponse.clone());
      }
      return networkResponse;
    }

    throw new Error(`Network response: ${networkResponse.status}`);
  } catch {
    // Network failed - try cache
    const cachedResponse = await cache.match(request);

    if (cachedResponse) {
      return new Response(await cachedResponse.blob(), {
        status: cachedResponse.status,
        statusText: cachedResponse.statusText,
        headers: {
          ...Object.fromEntries(cachedResponse.headers.entries()),
          'X-Offline': 'true',
          'X-Stale-Data': 'true',
        },
      });
    }

    // For POST/PUT (visit creation), queue for later sync
    if (request.method !== 'GET') {
      await queueOfflineRequest(request);
      return new Response(
        JSON.stringify({ queued: true, message: 'Request queued for sync when online' }),
        { status: 202, headers: { 'Content-Type': 'application/json' } }
      );
    }

    // No cache available for GET
    return new Response(
      JSON.stringify({ error: 'Offline', message: 'No cached data available' }),
      { status: 503, headers: { 'Content-Type': 'application/json' } }
    );
  }
}

async function handleMapRequest(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  const network = fetch(request).then((response) => {
    if (response.ok) cache.put(request, response.clone());
    return response;
  }).catch(() => cached || new Response('', { status: 503 }));
  return cached || network;
}

async function handleStaticRequest(request) {
  const cache = await caches.open(CACHE_NAME);
  const cachedResponse = await cache.match(request);

  if (cachedResponse) {
    return cachedResponse;
  }

  try {
    const networkResponse = await fetch(request);
    if (networkResponse.ok) {
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch {
    return new Response('Offline', { status: 503 });
  }
}

async function queueOfflineRequest(request) {
  const db = await openOfflineDB();
  const body = await request.clone().text();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction([OFFLINE_QUEUE_STORE], 'readwrite');
    const store = transaction.objectStore(OFFLINE_QUEUE_STORE);

    const requestData = {
      url: request.url,
      method: request.method,
      headers: [...request.headers.entries()],
      body,
      timestamp: Date.now(),
      retries: 0,
    };

    const addRequest = store.add(requestData);
    addRequest.onsuccess = () => resolve(addRequest.result);
    addRequest.onerror = () => reject(addRequest.error);
  });
}

function openOfflineDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(OFFLINE_QUEUE_DB, 1);

    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains(OFFLINE_QUEUE_STORE)) {
        const store = db.createObjectStore(OFFLINE_QUEUE_STORE, { keyPath: 'id', autoIncrement: true });
        store.createIndex('timestamp', 'timestamp', { unique: false });
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

// Background sync for queued requests
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-offline-visits') {
    event.waitUntil(syncOfflineVisits());
  }
});

async function syncOfflineVisits() {
  const db = await openOfflineDB();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction([OFFLINE_QUEUE_STORE], 'readwrite');
    const store = transaction.objectStore(OFFLINE_QUEUE_STORE);
    const getAllRequest = store.getAll();

    getAllRequest.onsuccess = async () => {
      const requests = getAllRequest.result;

      for (const queuedRequest of requests) {
        try {
          const request = new Request(queuedRequest.url, {
            method: queuedRequest.method,
            headers: new Headers(queuedRequest.headers),
            body: queuedRequest.body,
          });

          const response = await fetch(request);

          if (response.ok) {
            // Remove from queue on success
            const deleteTransaction = db.transaction([OFFLINE_QUEUE_STORE], 'readwrite');
            const deleteStore = deleteTransaction.objectStore(OFFLINE_QUEUE_STORE);
            deleteStore.delete(queuedRequest.id);
          } else {
            // Increment retry count
            queuedRequest.retries++;
            if (queuedRequest.retries >= 5) {
              // Max retries reached, could move to dead letter queue
              console.error('Max retries reached for:', queuedRequest.url);
            } else {
              const updateTransaction = db.transaction([OFFLINE_QUEUE_STORE], 'readwrite');
              const updateStore = updateTransaction.objectStore(OFFLINE_QUEUE_STORE);
              updateStore.put(queuedRequest);
            }
          }
        } catch (error) {
          console.error('Sync failed for:', queuedRequest.url, error);
        }
      }

      resolve();
    };

    getAllRequest.onerror = () => reject(getAllRequest.error);
  });
}

// Periodic sync check
self.addEventListener('periodicsync', (event) => {
  if (event.tag === 'periodic-sync-visits') {
    event.waitUntil(syncOfflineVisits());
  }
});