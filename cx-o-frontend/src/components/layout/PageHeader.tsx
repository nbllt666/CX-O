import React from 'react';
import { cn } from '../../lib/utils';

interface PageHeaderProps {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  breadcrumbs?: { label: string; path?: string }[];
  className?: string;
}

export const PageHeader: React.FC<PageHeaderProps> = ({
  title,
  description,
  actions,
  breadcrumbs,
  className,
}) => (
  <div className={cn('mb-6', className)}>
    {breadcrumbs && breadcrumbs.length > 0 && (
      <nav className="mb-2 text-sm text-[var(--color-text-tertiary)]">
        <ol className="flex items-center gap-2">
          {breadcrumbs.map((crumb, index) => (
            <li key={index} className="flex items-center gap-2">
              {index > 0 && <span>/</span>}
              {crumb.path ? (
                <a
                  href={crumb.path}
                  className="hover:text-[var(--color-text-primary)] transition-colors"
                >
                  {crumb.label}
                </a>
              ) : (
                <span>{crumb.label}</span>
              )}
            </li>
          ))}
        </ol>
      </nav>
    )}
    <div className="flex items-center justify-between">
      <div>
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">{title}</h1>
        {description && (
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">{description}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  </div>
);
