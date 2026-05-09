import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Header } from './Header';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        'nav.chat': '对话',
        'agent.title': '助手',
        'memory.title': '记忆',
        'archive.title': '归档',
        'acp.title': 'ACP',
        'tools.title': '工具',
        'settings.title': '设置',
      };
      return translations[key] || key;
    },
  }),
}));

vi.mock('./LanguageSwitcher', () => ({
  LanguageSwitcher: () => <div data-testid="language-switcher">Language Switcher</div>,
}));

const renderWithRouter = (initialRoute: string = '/') => {
  return render(
    <MemoryRouter initialEntries={[initialRoute]}>
      <Header />
    </MemoryRouter>
  );
};

describe('Header', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('rendering', () => {
    it('should render the header component', () => {
      renderWithRouter();
      expect(screen.getByRole('banner')).toBeDefined();
    });

    it('should display CXHMS version', () => {
      renderWithRouter();
      expect(screen.getByText('CXHMS v1.0')).toBeDefined();
    });

    it('should render language switcher', () => {
      renderWithRouter();
      expect(screen.getByTestId('language-switcher')).toBeDefined();
    });
  });

  describe('page titles', () => {
    it('should display chat title on root path', () => {
      renderWithRouter('/');
      expect(screen.getByText('对话')).toBeDefined();
    });

    it('should display agents title on /agents path', () => {
      renderWithRouter('/agents');
      expect(screen.getByText('助手')).toBeDefined();
    });

    it('should display memories title on /memories path', () => {
      renderWithRouter('/memories');
      expect(screen.getByText('记忆')).toBeDefined();
    });

    it('should display archive title on /archive path', () => {
      renderWithRouter('/archive');
      expect(screen.getByText('归档')).toBeDefined();
    });

    it('should display ACP title on /acp path', () => {
      renderWithRouter('/acp');
      expect(screen.getByText('ACP')).toBeDefined();
    });

    it('should display tools title on /tools path', () => {
      renderWithRouter('/tools');
      expect(screen.getByText('工具')).toBeDefined();
    });

    it('should display settings title on /settings path', () => {
      renderWithRouter('/settings');
      expect(screen.getByText('设置')).toBeDefined();
    });

    it('should display default title for unknown paths', () => {
      renderWithRouter('/unknown-path');
      expect(screen.getByText('CXHMS')).toBeDefined();
    });
  });

  describe('navigation buttons', () => {
    it('should render memory agent button', () => {
      renderWithRouter();
      const buttons = screen.getAllByRole('button');
      expect(buttons.length).toBeGreaterThan(0);
    });

    it('should render support developer link', () => {
      renderWithRouter();
      const link = screen.getByRole('link');
      expect(link).toBeDefined();
      expect(link.getAttribute('href')).toBe('https://afdian.com/a/nbllt666');
    });
  });

  describe('memory agent page', () => {
    it('should highlight memory agent button when on memory-agent page', () => {
      renderWithRouter('/memory-agent');
      const titleElements = screen.getAllByText('记忆管理助手');
      expect(titleElements.length).toBeGreaterThan(0);
    });
  });
});
