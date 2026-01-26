/**
 * Tests for Header component
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Header } from '../Header';

// Mock fetch
global.fetch = vi.fn();

describe('Header component', () => {
  const mockOnSelectRoute = vi.fn();
  const defaultProps = {
    onSelectRoute: mockOnSelectRoute,
    selectedRouteNumber: null,
    loading: false,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    (global.fetch as any).mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('should render header with search input', () => {
    render(<Header {...defaultProps} />);
    expect(screen.getByPlaceholderText(/søk etter rute/i)).toBeInTheDocument();
  });

  it('should display selected route number in search', () => {
    render(<Header {...defaultProps} selectedRouteNumber="BRE001" />);
    const input = screen.getByPlaceholderText(/søk etter rute/i) as HTMLInputElement;
    expect(input.value).toBe('BRE001');
  });

  it('should search for routes when typing', async () => {
    vi.useFakeTimers();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const mockRoutes = [
      { rutenummer: 'BRE001', rutenavn: 'Test Route 1' },
      { rutenummer: 'BRE002', rutenavn: 'Test Route 2' },
    ];

    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ routes: mockRoutes }),
    });

    render(<Header {...defaultProps} />);
    const input = screen.getByPlaceholderText(/søk etter rute/i);

    await act(async () => {
      await user.type(input, 'BR');
      await vi.runAllTimersAsync();
    });
    await Promise.resolve();

    expect(global.fetch).toHaveBeenCalled();
  });

  it('should list all routes when search is empty', async () => {
    const mockRoutes = [
      { rutenummer: 'BRE001', rutenavn: 'Route 1' },
      { rutenummer: 'BRE002', rutenavn: 'Route 2' },
    ];

    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ routes: mockRoutes }),
    });

    vi.useFakeTimers();
    render(<Header {...defaultProps} />);
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    await Promise.resolve();

    expect(global.fetch).toHaveBeenCalled();
  });

  it('should call onSelectRoute when route is clicked', async () => {
    vi.useFakeTimers();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const mockRoutes = [
      { rutenummer: 'BRE001', rutenavn: 'Test Route' },
    ];

    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ routes: mockRoutes }),
    });

    render(<Header {...defaultProps} />);
    const input = screen.getByPlaceholderText(/søk etter rute/i);

    await act(async () => {
      await user.type(input, 'BR');
      await vi.runAllTimersAsync();
    });
    await Promise.resolve();

    await Promise.resolve();
    const routeItem = screen.getByText('BRE001');
    await act(async () => {
      await user.click(routeItem);
    });

    expect(mockOnSelectRoute).toHaveBeenCalledWith('BRE001');
  });

  it('should show save button when changeset exists', () => {
    const changeset = { id: 'test-123', status: 'draft' };
    const mockOnSave = vi.fn();

    render(<Header {...defaultProps} changeset={changeset} onSaveChanges={mockOnSave} />);

    expect(screen.getByText(/lagre til fil/i)).toBeInTheDocument();
  });

  it('should show publish button when local events exist', () => {
    const mockOnPublish = vi.fn();

    render(<Header {...defaultProps} localEventsCount={3} onPublish={mockOnPublish} />);

    expect(screen.getByText(/publiser/i)).toBeInTheDocument();
  });
});
