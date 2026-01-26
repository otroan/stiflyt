/**
 * Notification container component for displaying toast notifications
 */
import { useState, useEffect, useRef } from 'react';
import { notificationManager, type Notification } from '../utils/notifications';
import './NotificationContainer.css';

export function NotificationContainer() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const timeoutRefs = useRef<Map<string, NodeJS.Timeout>>(new Map());

  useEffect(() => {
    console.log('[NotificationContainer] Setting up subscription');
    const unsubscribe = notificationManager.subscribe((notification) => {
      console.log('[NotificationContainer] Received notification event:', notification.id, notification.message);
      if (notification.id === 'clear') {
        console.log('[NotificationContainer] Clearing all notifications');
        // Clear all timeouts
        timeoutRefs.current.forEach(timeout => clearTimeout(timeout));
        timeoutRefs.current.clear();
        setNotifications([]);
      } else if (notification.id.startsWith('dismiss-')) {
        // Handle dismiss event - remove the notification
        const originalId = notification.id.replace('dismiss-', '');
        console.log('[NotificationContainer] Handling dismiss for', originalId);
        // Clear timeout if it exists
        const timeout = timeoutRefs.current.get(originalId);
        if (timeout) {
          console.log('[NotificationContainer] Clearing timeout for', originalId);
          clearTimeout(timeout);
          timeoutRefs.current.delete(originalId);
        }
        setNotifications((prev) => {
          const filtered = prev.filter((n) => n.id !== originalId);
          console.log('[NotificationContainer] After dismiss filter - prev count:', prev.length, 'new count:', filtered.length);
          return filtered;
        });
      } else {
        console.log('[NotificationContainer] Adding/updating notification:', notification.id);
        setNotifications((prev) => {
          // Check if notification already exists (update case)
          const exists = prev.find((n) => n.id === notification.id);
          if (exists) {
            console.log('[NotificationContainer] Updating existing notification');
            return prev.map((n) => (n.id === notification.id ? notification : n));
          }
          // Add new notification
          console.log('[NotificationContainer] Adding new notification, prev count:', prev.length);
          return [...prev, notification];
        });
      }
    });

    // Load initial notifications
    const initial = notificationManager.getNotifications();
    console.log('[NotificationContainer] Loaded initial notifications:', initial.length);
    setNotifications(initial);

    return unsubscribe;
  }, []);

  // Handle auto-dismiss for each notification
  useEffect(() => {
    console.log('[NotificationContainer] Auto-dismiss effect running, notifications count:', notifications.length);
    notifications.forEach((notification) => {
      // Skip if already has a timeout
      if (timeoutRefs.current.has(notification.id)) {
        console.log('[NotificationContainer] Skipping', notification.id, '- already has timeout');
        return;
      }

      // Set up auto-dismiss if duration is set and > 0
      if (notification.duration && notification.duration > 0) {
        console.log('[NotificationContainer] Setting up auto-dismiss for', notification.id, 'in', notification.duration, 'ms');
        const timeout = setTimeout(() => {
          console.log('[NotificationContainer] Auto-dismiss timeout fired for', notification.id);
          notificationManager.dismiss(notification.id);
          timeoutRefs.current.delete(notification.id);
        }, notification.duration);
        
        timeoutRefs.current.set(notification.id, timeout);
        console.log('[NotificationContainer] Timeout set for', notification.id);
      } else {
        console.log('[NotificationContainer] No auto-dismiss for', notification.id, '(duration:', notification.duration, ')');
      }
    });

    // Cleanup function to clear timeouts for removed notifications
    return () => {
      const currentIds = new Set(notifications.map(n => n.id));
      timeoutRefs.current.forEach((timeout, id) => {
        if (!currentIds.has(id)) {
          console.log('[NotificationContainer] Cleaning up timeout for removed notification:', id);
          clearTimeout(timeout);
          timeoutRefs.current.delete(id);
        }
      });
    };
  }, [notifications]);

  const handleDismiss = (id: string) => {
    console.log('[NotificationContainer] handleDismiss called for', id);
    notificationManager.dismiss(id);
    setNotifications((prev) => {
      const filtered = prev.filter((n) => n.id !== id);
      console.log('[NotificationContainer] After manual dismiss - prev count:', prev.length, 'new count:', filtered.length);
      return filtered;
    });
  };

  return (
    <div className="notification-container">
      {notifications.map((notification) => (
        <div
          key={notification.id}
          className={`notification notification-${notification.type}`}
          role="alert"
          aria-live="polite"
        >
          <div className="notification-content">
            <div className="notification-icon">
              {notification.type === 'success' && '✓'}
              {notification.type === 'error' && '✕'}
              {notification.type === 'warning' && '⚠'}
              {notification.type === 'info' && 'ℹ'}
            </div>
            <div className="notification-message">{notification.message}</div>
            {notification.action && (
              <button
                className="notification-action"
                onClick={notification.action.onClick}
              >
                {notification.action.label}
              </button>
            )}
          </div>
          <button
            className="notification-close"
            onClick={() => handleDismiss(notification.id)}
            aria-label="Lukk varsel"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
