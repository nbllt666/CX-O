import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { AppLayout } from './AppLayout';

vi.mock('./layout/Sidebar', () => ({
  Sidebar: () => <div data-testid="sidebar">Sidebar</div>,
}));

vi.mock('./layout/Header', () => ({
  Header: () => <div data-testid="header">Header</div>,
}));

const renderWithRouter = (initialRoute: string = '/') => {
  return render(
    <MemoryRouter initialEntries={[initialRoute]}>
      <Routes>
        <Route path="/" element={<AppLayout />}>
          <Route index element={<div>Home Content</div>} />
        </Route>
        <Route path="/agents" element={<AppLayout />}>
          <Route index element={<div>Agents Content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
};

describe('AppLayout', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('rendering', () => {
    it('should render the layout component', () => {
      renderWithRouter();
      expect(screen.getByTestId('sidebar')).toBeDefined();
      expect(screen.getByTestId('header')).toBeDefined();
    });

    it('should render sidebar', () => {
      renderWithRouter();
      expect(screen.getByText('Sidebar')).toBeDefined();
    });

    it('should render header', () => {
      renderWithRouter();
      expect(screen.getByText('Header')).toBeDefined();
    });

    it('should render main content area', () => {
      renderWithRouter();
      expect(screen.getByText('Home Content')).toBeDefined();
    });
  });

  describe('routing', () => {
    it('should render home content on root path', () => {
      renderWithRouter('/');
      expect(screen.getByText('Home Content')).toBeDefined();
    });

    it('should render agents content on /agents path', () => {
      renderWithRouter('/agents');
      expect(screen.getByText('Agents Content')).toBeDefined();
    });
  });
});
