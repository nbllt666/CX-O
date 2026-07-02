import { Button, Badge, Drawer } from '../../components/ui';
import { formatDate, getImportanceLabel } from '../../lib/utils';
import type { Memory } from './types';
import { typeLabels } from './types';

interface MemoryDetailDrawerProps {
  memory: Memory;
  onClose: () => void;
  onEdit: (memory: Memory) => void;
  onArchive: (id: number) => void;
  onDelete: (id: number) => void;
}

export function MemoryDetailDrawer({
  memory,
  onClose,
  onEdit,
  onArchive,
  onDelete,
}: MemoryDetailDrawerProps) {
  return (
    <Drawer isOpen onClose={onClose} title="记忆详情">
      <div className="space-y-4">
        <div>
          <h3 className="text-sm font-medium text-[var(--color-text-secondary)] mb-2">内容</h3>
          <p className="text-[var(--color-text-primary)] whitespace-pre-wrap">
            {memory.content}
          </p>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <h3 className="text-sm font-medium text-[var(--color-text-secondary)] mb-2">
              类型
            </h3>
            <Badge variant="secondary">
              {typeLabels[memory.type] || memory.type}
            </Badge>
          </div>
          <div>
            <h3 className="text-sm font-medium text-[var(--color-text-secondary)] mb-2">
              重要性
            </h3>
            <span>{getImportanceLabel(memory.importance)}</span>
          </div>
        </div>
        <div>
          <h3 className="text-sm font-medium text-[var(--color-text-secondary)] mb-2">标签</h3>
          <div className="flex gap-2 flex-wrap">
            {memory.tags?.map((tag) => (
              <Badge key={tag} variant="primary">
                {tag}
              </Badge>
            ))}
            {(!memory.tags || memory.tags.length === 0) && (
              <span className="text-[var(--color-text-tertiary)]">无标签</span>
            )}
          </div>
        </div>
        <div>
          <h3 className="text-sm font-medium text-[var(--color-text-secondary)] mb-2">
            创建时间
          </h3>
          <span className="text-[var(--color-text-primary)]">
            {formatDate(memory.created_at)}
          </span>
        </div>
        <div className="flex gap-2 pt-4 border-t border-[var(--color-border)]">
          <Button
            variant="secondary"
            onClick={() => {
              onClose();
              onEdit(memory);
            }}
          >
            编辑
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              onArchive(memory.id);
              onClose();
            }}
          >
            归档
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              onDelete(memory.id);
              onClose();
            }}
          >
            删除
          </Button>
        </div>
      </div>
    </Drawer>
  );
}
