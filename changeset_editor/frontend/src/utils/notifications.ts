/**
 * Notification system for user-friendly error and success messages
 * Replaces alert() calls with toast-style notifications
 */

export type NotificationType = 'success' | 'error' | 'warning' | 'info';

export interface Notification {
  id: string;
  type: NotificationType;
  message: string;
  duration?: number; // Auto-dismiss after milliseconds (0 = no auto-dismiss)
  action?: {
    label: string;
    onClick: () => void;
  };
}

type NotificationListener = (notification: Notification) => void;

class NotificationManager {
  private listeners: Set<NotificationListener> = new Set();
  private notifications: Map<string, Notification> = new Map();

  /**
   * Subscribe to notification events
   */
  subscribe(listener: NotificationListener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  /**
   * Get all current notifications
   */
  getNotifications(): Notification[] {
    return Array.from(this.notifications.values());
  }

  /**
   * Show a notification
   */
  show(notification: Omit<Notification, 'id'>): string {
    const id = `notification-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    const fullNotification: Notification = {
      id,
      duration: notification.duration ?? 5000, // Default 5 seconds
      ...notification,
    };

    this.notifications.set(id, fullNotification);
    this.notifyListeners(fullNotification);

    // Auto-dismiss if duration is set
    if (fullNotification.duration && fullNotification.duration > 0) {
      setTimeout(() => {
        this.dismiss(id);
      }, fullNotification.duration);
    }

    return id;
  }

  /**
   * Dismiss a notification
   */
  dismiss(id: string): void {
    if (this.notifications.has(id)) {
      this.notifications.delete(id);
      // Notify listeners that notification was dismissed
      this.listeners.forEach(listener => {
        listener({ id, type: 'info', message: '' } as Notification);
      });
    }
  }

  /**
   * Clear all notifications
   */
  clear(): void {
    this.notifications.clear();
    this.listeners.forEach(listener => {
      listener({ id: 'clear', type: 'info', message: '' } as Notification);
    });
  }

  /**
   * Convenience methods
   */
  success(message: string, duration?: number): string {
    return this.show({ type: 'success', message, duration });
  }

  error(message: string, duration?: number): string {
    return this.show({ type: 'error', message, duration: duration ?? 0 }); // Errors don't auto-dismiss by default
  }

  warning(message: string, duration?: number): string {
    return this.show({ type: 'warning', message, duration });
  }

  info(message: string, duration?: number): string {
    return this.show({ type: 'info', message, duration });
  }

  private notifyListeners(notification: Notification): void {
    this.listeners.forEach(listener => {
      listener(notification);
    });
  }
}

// Singleton instance
export const notificationManager = new NotificationManager();

// React hook for using notifications in components
export function useNotifications() {
  return {
    show: (notification: Omit<Notification, 'id'>) => notificationManager.show(notification),
    success: (message: string, duration?: number) => notificationManager.success(message, duration),
    error: (message: string, duration?: number) => notificationManager.error(message, duration),
    warning: (message: string, duration?: number) => notificationManager.warning(message, duration),
    info: (message: string, duration?: number) => notificationManager.info(message, duration),
    dismiss: (id: string) => notificationManager.dismiss(id),
    clear: () => notificationManager.clear(),
  };
}
