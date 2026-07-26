import { Card, CardBody, Badge } from '@/components/ui-v2';
import {
  formatDate,
  truncate,
  getImportanceColor,
  getImportanceLabel,
} from '../../lib/utils';
import type { Memory } from './types';
import { typeLabels } from './types';

interface MemoryCardProps {
  memory: Memory;
  isBatchMode: boolean;
  isSelected: boolean;
  onView: (memory: Memory) => void;
  onEdit: (memory: Memory) => void;
  onDelete: (id: number) => void;
  onArchive: (id: number) => void;
  onToggleSelect: (id: number) => void;
}

export function MemoryCard({
  memory,
  isBatchMode,
  isSelected,
  onView,
  onEdit,
  onDelete,
  onArchive,
  onToggleSelect,
}: MemoryCardProps) {
  return (
    <Card
      className={`cursor-pointer transition-all hover:shadow-lg ${
        memory.is_archived ? 'opacity-60' : ''
      } ${isBatchMode && isSelected ? 'ring-2 ring-[var(--color-accent)]' : ''}`}
      onClick={() => {
        if (isBatchMode) {
          onToggleSelect(memory.id);
        } else {
          onView(memory);
        }
      }}
    >
      <CardBody>
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-2">
            <span
              className="w-2 h-2 rounded-full"
              style={{
                backgroundColor: `var(--color-${getImportanceColor(memory.importance).replace('bg-', '')})`,
              }}
            />
            <span className="text-xs text-[var(--color-text-secondary)]">
              {getImportanceLabel(memory.importance)}
            </span>
            <Badge variant="secondary" size="sm">
              {typeLabels[memory.type] || memory.type}
            </Badge>
          </div>
          {!isBatchMode && (
            <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
              <button
                onClick={() => onArchive(memory.id)}
                className="p-1.5 hover:bg-[var(--color-bg-hover)] rounded-[var(--radius-sm)] transition-colors"
                title="归档"
              >
                <svg className="w-4 h-4 text-[var(--color-text-secondary)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" />
                </svg>
              </button>
              <button
                onClick={() => onEdit(memory)}
                className="p-1.5 hover:bg-[var(--color-bg-hover)] rounded-[var(--radius-sm)] transition-colors"
                title="编辑"
              >
                <svg className="w-4 h-4 text-[var(--color-text-secondary)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                </svg>
              </button>
              <button
                onClick={() => onDelete(memory.id)}
                className="p-1.5 hover:bg-[var(--color-error-light)] rounded-[var(--radius-sm)] transition-colors"
                title="删除"
              >
                <svg className="w-4 h-4 text-[var(--color-error)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            </div>
          )}
        </div>
        <p className="text-sm text-[var(--color-text-primary)] mb-3 line-clamp-4">
          {truncate(memory.content, 200)}
        </p>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1 flex-wrap">
            {memory.tags?.slice(0, 3).map((tag) => (
              <Badge key={tag} variant="anime" size="sm">
                {tag}
              </Badge>
            ))}
            {memory.tags && memory.tags.length > 3 && (
              <span className="text-xs text-[var(--color-text-tertiary)]">
                +{memory.tags.length - 3}
              </span>
            )}
          </div>
          <span className="text-xs text-[var(--color-text-tertiary)]">
            {formatDate(memory.created_at)}
          </span>
        </div>
      </CardBody>
    </Card>
  );
}
