import { Modal, Input, Button } from '../../components/ui';

interface BatchTagModalProps {
  selectedCount: number;
  operation: 'add' | 'remove' | 'set';
  tags: string;
  onOperationChange: (op: 'add' | 'remove' | 'set') => void;
  onTagsChange: (tags: string) => void;
  onConfirm: () => void;
  onClose: () => void;
}

export function BatchTagModal({
  selectedCount,
  operation,
  tags,
  onOperationChange,
  onTagsChange,
  onConfirm,
  onClose,
}: BatchTagModalProps) {
  return (
    <Modal isOpen onClose={onClose} title="批量更新标签">
      <div className="space-y-4">
        <p className="text-sm text-[var(--color-text-secondary)]">
          将对选中的 {selectedCount} 条记忆进行标签操作
        </p>
        <div>
          <label className="text-sm font-medium mb-1.5 block">操作类型</label>
          <select
            value={operation}
            onChange={(e) => onOperationChange(e.target.value as BatchTagModalProps['operation'])}
            className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
          >
            <option value="add">添加标签</option>
            <option value="remove">移除标签</option>
            <option value="set">设置标签（覆盖现有）</option>
          </select>
        </div>
        <div>
          <label className="text-sm font-medium mb-1.5 block">标签（用逗号分隔）</label>
          <Input
            value={tags}
            onChange={(e) => onTagsChange(e.target.value)}
            placeholder="标签1, 标签2, 标签3"
          />
        </div>
        <div className="flex justify-end gap-3 pt-4">
          <Button variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button onClick={onConfirm} disabled={!tags.trim()}>
            确认
          </Button>
        </div>
      </div>
    </Modal>
  );
}
