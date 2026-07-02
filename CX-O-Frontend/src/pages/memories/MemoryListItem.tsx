import { Badge } from '../../components/ui';
import {
  formatDate,
  truncate,
  getImportanceLabel,
} from '../../lib/utils';
import type { Memory } from './types';
import { typeLabels } from './types';

interface MemoryListItemProps {
  memory: Memory;
  isBatchMode: boolean;
  isSelected: boolean;
  onView: (memory: Memory) => void;
  onEdit: (memory: Memory) => void;
  onDelete: (id: number) => void;
  onToggleSelect: (id: number) => void;
}

export function MemoryListItem({
  memory,
  isBatchMode,
  isSelected,
  onView,
  onEdit,
  onDelete,
  onToggleSelect,
}: MemoryListItemProps) {
  return (
    <tr
      className={`hover:bg-[var(--color-bg-hover)] cursor-pointer ${
        isBatchMode && isSelected ? 'bg-[var(--color-accent-light)]' : ''
      }`}
      onClick={() => {
        if (isBatchMode) {
          onToggleSelect(memory.id);
        } else {
          onView(memory);
        }
      }}
    >
      {isBatchMode && (
        <td className="px-4 py-3">
          <input
            type="checkbox"
            checked={isSelected}
            onChange={() => onToggleSelect(memory.id)}
            className="rounded"
          />
        </td>
      )}
      <td className="px-4 py-3 text-sm truncate max-w-xs">
        {truncate(memory.content, 100)}
      </td>
      <td className="px-4 py-3">
        <Badge variant="secondary" size="sm">
          {typeLabels[memory.type] || memory.type}
        </Badge>
      </td>
      <td className="px-4 py-3 text-sm">{getImportanceLabel(memory.importance)}</td>
      <td className="px-4 py-3">
        <div className="flex gap-1 flex-wrap">
          {memory.tags?.slice(0, 2).map((tag) => (
            <Badge key={tag} variant="primary" size="sm">
              {tag}
            </Badge>
          ))}
          {memory.tags && memory.tags.length > 2 && (
            <span className="text-xs text-[var(--color-text-tertiary)]">
              +{memory.tags.length - 2}
            </span>
          )}
        </div>
      </td>
      <td className="px-4 py-3 text-sm text-[var(--color-text-secondary)]">
        {formatDate(memory.created_at)}
      </td>
      <td className="px-4 py-3 text-right">
        <div
          className="flex items-center justify-end gap-1"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={() => onEdit(memory)}
            className="p-1.5 hover:bg-[var(--color-bg-hover)] rounded-[var(--radius-sm)]"
          >
            <svg className="w-4 h-4 text-[var(--color-text-secondary)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
            </svg>
          </button>
          <button
            onClick={() => onDelete(memory.id)}
            className="p-1.5 hover:bg-[var(--color-error-light)] rounded-[var(--radius-sm)]"
          >
            <svg className="w-4 h-4 text-[var(--color-error)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
          </button>
        </div>
      </td>
    </tr>
  );
}
