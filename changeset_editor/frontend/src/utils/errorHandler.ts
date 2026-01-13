/**
 * Centralized error handling utilities
 */

export interface AppError {
  message: string;
  code?: string;
  statusCode?: number;
  originalError?: unknown;
  retryable?: boolean;
}

export type ErrorSeverity = 'error' | 'warning' | 'info';

/**
 * Extract user-friendly error message from various error types
 */
export function extractErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === 'string') {
    return error;
  }
  if (error && typeof error === 'object' && 'message' in error) {
    return String((error as any).message);
  }
  if (error && typeof error === 'object' && 'detail' in error) {
    return String((error as any).detail);
  }
  return 'En ukjent feil oppstod';
}

/**
 * Extract error code from various error types
 */
export function extractErrorCode(error: unknown): string | undefined {
  if (error && typeof error === 'object') {
    if ('code' in error) {
      return String((error as any).code);
    }
    if ('statusCode' in error) {
      return `HTTP_${(error as any).statusCode}`;
    }
  }
  return undefined;
}

/**
 * Check if error is retryable (network errors, 5xx status codes)
 */
export function isRetryableError(error: unknown): boolean {
  if (error && typeof error === 'object') {
    // Network errors
    if (error instanceof TypeError && error.message.includes('fetch')) {
      return true;
    }
    // 5xx server errors
    if ('statusCode' in error) {
      const status = (error as any).statusCode;
      return status >= 500 && status < 600;
    }
    // 429 Too Many Requests
    if ('status' in error) {
      const status = (error as any).status;
      return status === 429 || (status >= 500 && status < 600);
    }
  }
  return false;
}

/**
 * Create a standardized AppError from various error types
 */
export function normalizeError(error: unknown, context?: string): AppError {
  const message = extractErrorMessage(error);
  const code = extractErrorCode(error);
  const retryable = isRetryableError(error);

  let statusCode: number | undefined;
  if (error && typeof error === 'object') {
    if ('statusCode' in error) {
      statusCode = (error as any).statusCode;
    } else if ('status' in error) {
      statusCode = (error as any).status;
    }
  }

  return {
    message: context ? `${context}: ${message}` : message,
    code,
    statusCode,
    originalError: error,
    retryable,
  };
}

/**
 * Log error to console (for debugging) and optionally to error service
 */
export function logError(error: AppError, context?: string): void {
  const logMessage = context 
    ? `[${context}] ${error.message}`
    : error.message;

  console.error(logMessage, {
    code: error.code,
    statusCode: error.statusCode,
    retryable: error.retryable,
    originalError: error.originalError,
  });

  // TODO: Integrate with error logging service (e.g., Sentry, LogRocket)
  // if (window.errorLogger) {
  //   window.errorLogger.captureException(error.originalError || error, {
  //     tags: { code: error.code, context },
  //   });
  // }
}

/**
 * Handle API errors with proper extraction and logging
 */
export function handleApiError(error: unknown, context?: string): AppError {
  const appError = normalizeError(error, context);
  logError(appError, context);
  return appError;
}
