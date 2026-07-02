import { useState } from 'react';
import { Modal, Textarea, Input, Button } from '../../components/ui';
import type { Memory } from './types';

interface MemoryFormModalProps {
  memory: Memory | null;
  onClose: () => void;
  onSave: (data: { content: string; type: string; importance: number; tags: string[] }) => void;
}

export function MemoryFormModal({ memory, onClose, onSave }: MemoryFormModalProps) {
  const isEdit = memory !== null;
  const [content, setContent] = useState(memory?.content || '');
  const [type, setType] = useState(memory?.type || 'long_term');
  const [importance, setImportance] = useState(memory?.importance || 3);
  const [tags, setTags] = useState(memory?.tags.join(', ') || '');

  const handleSave = () => {
    if (!content.trim()) return;
    onSave({
      content,
      type,
      importance,
      tags: tags
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean),
    });
  };

  return (
    <Modal isOpen onClose={onClose} title={isEdit ? '编辑记忆' : '新建记忆'}>
      <div className="space-y-4">
        <div>
          <label className="text-sm font-medium mb-1.5 block">内容</label>
          <Textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="输入记忆内容..."
            className="min-h-[100px]"
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          {!isEdit && (
            <div>
              <label className="text-sm font-medium mb-1.5 block">类型</label>
              <select
                value={type}
                onChange={(e) => setType(e.target.value)}
                className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
              >
                <option value="long_term">长期记忆</option>
                <option value="short_term">短期记忆</option>
                <option value="permanent">永久记忆</option>
              </select>
            </div>
          )}
          <div>
            <label className="text-sm font-medium mb-1.5 block">重要性</label>
            <div className="flex items-center gap-1">
              {[1, 2, 3, 4, 5].map((star) => (
                <button
                  key={star}
                  onClick={() => setImportance(star)}
                  className="p-1"
                >
                  <svg
                    className={`w-5 h-5 ${star <= importance ? 'fill-yellow-400 text-yellow-400' : 'text-[var(--color-text-tertiary)]'}`}
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z"
                    />
                  </svg>
                </button>
              ))}
            </div>
          </div>
        </div>
        <div>
          <label className="text-sm font-medium mb-1.5 block">标签（用逗号分隔）</label>
          <Input
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="标签1, 标签2, 标签3"
          />
        </div>
        <div className="flex justify-end gap-3 pt-4">
          <Button variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button onClick={handleSave} disabled={!content.trim()}>
            {isEdit ? '保存' : '创建'}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
