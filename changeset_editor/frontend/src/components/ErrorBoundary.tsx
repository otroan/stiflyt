/**
 * Error Boundary component for catching React errors
 */
import { Component, ErrorInfo, ReactNode } from 'react';
import { handleApiError } from '../utils/errorHandler';
import { notificationManager } from '../utils/notifications';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error: Error): State {
    return {
      hasError: true,
      error,
      errorInfo: null,
    };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // Log error
    const appError = handleApiError(error, 'React Error Boundary');
    console.error('Error caught by boundary:', error, errorInfo);

    // Show notification
    notificationManager.error(
      `En uventet feil oppstod: ${appError.message}. Siden kan være ufullstendig.`
    );

    this.setState({
      error,
      errorInfo,
    });

    // TODO: Send to error logging service
    // if (window.errorLogger) {
    //   window.errorLogger.captureException(error, {
    //     contexts: { react: { componentStack: errorInfo.componentStack } },
    //   });
    // }
  }

  handleReset = (): void => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    });
  };

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div
          style={{
            padding: '2rem',
            textAlign: 'center',
            maxWidth: '600px',
            margin: '2rem auto',
          }}
        >
          <h2 style={{ color: '#dc3545', marginBottom: '1rem' }}>
            Noe gikk galt
          </h2>
          <p style={{ color: '#666', marginBottom: '1.5rem' }}>
            En uventet feil oppstod. Vennligst prøv å oppdatere siden.
          </p>
          {this.state.error && (
            <details
              style={{
                textAlign: 'left',
                marginBottom: '1.5rem',
                padding: '1rem',
                background: '#f8f9fa',
                borderRadius: '4px',
                fontSize: '0.9em',
              }}
            >
              <summary style={{ cursor: 'pointer', marginBottom: '0.5rem' }}>
                Tekniske detaljer
              </summary>
              <pre
                style={{
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  color: '#dc3545',
                }}
              >
                {this.state.error.toString()}
                {this.state.errorInfo?.componentStack}
              </pre>
            </details>
          )}
          <button
            onClick={this.handleReset}
            style={{
              padding: '0.75rem 1.5rem',
              fontSize: '1rem',
              backgroundColor: '#007bff',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
            }}
          >
            Prøv igjen
          </button>
          <button
            onClick={() => window.location.reload()}
            style={{
              padding: '0.75rem 1.5rem',
              fontSize: '1rem',
              backgroundColor: '#6c757d',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              marginLeft: '0.5rem',
            }}
          >
            Oppdater siden
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
