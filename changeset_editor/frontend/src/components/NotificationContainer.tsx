/**
 * Notification container component for displaying toast notifications
 */
import { useState, useEffect } from 'react';
import { notificationManager, type Notification } from '../utils/notifications';
import './NotificationContainer.css';

export function NotificationContainer() {
  const [notifications, setNotifications] = useState<Notification[]>([]);

  useEffect(() => {
    const unsubscribe = notificationManager.subscribe((notification) => {
      if (notification.id === 'clear') {
        setNotifications([]);
      } else {
        setNotifications((prev) => {
          // Check if notification already exists (update case)
          const exists = prev.find((n) => n.id === notification.id);
          if (exists) {
            return prev.map((n) => (n.id === notification.id ? notification : n));
          }
          // Add new notification
          return [...prev, notification];
        });
      }
    });

    // Load initial notifications
    setNotifications(notificationManager.getNotifications());

    return unsubscribe;
  }, []);

  const handleDismiss = (id: string) => {
    notificationManager.dismiss(id);
    setNotifications((prev) => prev.filter((n) => n.id !== id));
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
