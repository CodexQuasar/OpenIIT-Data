import { useState, useEffect } from 'react';

export function OfflineIndicator() {
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [pendingCount, setPendingCount] = useState(0);

  useEffect(() => {
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  useEffect(() => {
    const updatePendingCount = async () => {
      try {
        const { offlineQueue } = await import('../utils/offlineQueue');
        const stats = await offlineQueue.getStats();
        setPendingCount(stats.pending);
      } catch {
        // Ignore errors
      }
    };

    updatePendingCount();
    const interval = setInterval(updatePendingCount, 30000); // Update every 30 seconds

    return () => clearInterval(interval);
  }, []);

  if (isOnline && pendingCount === 0) {
    return null;
  }

  return (
    <div
      className={`fixed bottom-4 right-4 z-50 flex items-center gap-2 px-3 py-2 rounded-lg shadow-lg transition-all ${
        isOnline 
          ? 'bg-amber-100 border border-amber-300 text-amber-800' 
          : 'bg-red-100 border border-red-300 text-red-800'
      }`}
      role="status"
      aria-live="polite"
    >
      <span className="flex items-center gap-1.5">
        {isOnline ? (
          <>
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span className="text-sm font-medium">Online</span>
            {pendingCount > 0 && (
              <>
                <span className="px-2 py-0.5 text-xs font-medium bg-amber-200 rounded-full">
                  {pendingCount} pending
                </span>
                <button
                  onClick={async () => {
                    const { offlineQueue } = await import('../utils/offlineQueue');
                    const result = await offlineQueue.syncAll();
                    console.log('Manual sync:', result);
                  }}
                  className="text-xs text-amber-700 hover:underline"
                >
                  Sync now
                </button>
              </>
            )}
          </>
        ) : (
          <>
            <svg className="w-4 h-4 animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 5.636l-3.536 3.536m0 5.656l3.536 3.536M9.172 9.172L5.636 5.636m3.536 9.192l-3.536 3.536M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span className="text-sm font-medium">Offline</span>
            {pendingCount > 0 && (
              <span className="px-2 py-0.5 text-xs font-medium bg-red-200 rounded-full">
                {pendingCount} queued
              </span>
            )}
          </>
        )}
      </span>
    </div>
  );
}