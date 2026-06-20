import { useState, useCallback, useRef } from 'react';
import { saveAvatar } from '../../services/avatarStorage';
import type { AvatarRecord } from '../../services/avatarStorage';
import { useSettingsStore } from '../../store/settingsStore';

interface AvatarUploaderProps {
  type: 'live2d' | 'vrm';
  onUploadSuccess?: (avatar: AvatarRecord) => void;
  onError?: (error: string) => void;
  maxFileSizeMb?: number;
}

export function AvatarUploader({ type, onUploadSuccess, onError, maxFileSizeMb }: AvatarUploaderProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const { limits } = useSettingsStore();
  const effectiveMaxFileSizeMb = maxFileSizeMb ?? limits?.max_upload_size_mb ?? 500;
  const MAX_FILE_SIZE = effectiveMaxFileSizeMb * 1024 * 1024;

  const validateFile = useCallback((file: File): string | null => {
    if (type === 'live2d') {
      const isValidLive2D =
        file.name.endsWith('.model.json') ||
        file.name.endsWith('.model3.json') ||
        file.name.endsWith('.zip');
      if (!isValidLive2D) {
        return 'Live2D 模型需要 .model.json 或 .zip 文件';
      }
    } else {
      if (!file.name.endsWith('.vrm')) {
        return 'VRM 模型需要 .vrm 文件';
      }
    }

    if (file.size > MAX_FILE_SIZE) {
      return `文件大小不能超过 ${effectiveMaxFileSizeMb}MB`;
    }

    return null;
  }, [type, MAX_FILE_SIZE, effectiveMaxFileSizeMb]);

  const processFile = useCallback(async (file: File) => {
    const validationError = validateFile(file);
    if (validationError) {
      onError?.(validationError);
      return;
    }

    setIsUploading(true);
    setUploadProgress(0);

    try {
      const avatar = await saveAvatar({
        file,
        name: file.name.replace(/\.[^.]+$/, ''),
        type,
        size: file.size,
        metadata: type === 'live2d' && file.name.endsWith('.zip') ? { modelJsonPath: undefined } : undefined,
      });

      setUploadProgress(100);
      onUploadSuccess?.(avatar);
    } catch (error) {
      console.error('Upload failed:', error);
      onError?.(error instanceof Error ? error.message : '上传失败');
    } finally {
      setIsUploading(false);
      setUploadProgress(0);
    }
  }, [type, validateFile, onUploadSuccess, onError]);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);

      const file = e.dataTransfer.files[0];
      if (file) {
        processFile(file);
      }
    },
    [processFile]
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) {
        processFile(file);
      }
      e.target.value = '';
    },
    [processFile]
  );

  const handleClick = useCallback(() => {
    inputRef.current?.click();
  }, []);

  const acceptTypes = type === 'live2d' ? '.model.json,.model3.json,.zip' : '.vrm';

  return (
    <div
      className={`relative border-2 border-dashed rounded-xl p-8 text-center transition-all cursor-pointer ${
        isDragging
          ? 'border-[var(--color-accent)] bg-[var(--color-accent)]/10'
          : 'border-[var(--color-border)] hover:border-[var(--color-accent)]/50'
      }`}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onClick={handleClick}
    >
      <input
        ref={inputRef}
        type="file"
        accept={acceptTypes}
        onChange={handleFileSelect}
        className="hidden"
      />

      {isUploading ? (
        <div className="space-y-3">
          <div className="w-12 h-12 mx-auto rounded-full border-2 border-[var(--color-accent)] border-t-transparent animate-spin" />
          <p className="text-sm text-[var(--color-text-secondary)]">上传中... {uploadProgress}%</p>
          <div className="w-full max-w-xs mx-auto h-2 bg-[var(--color-bg-tertiary)] rounded-full overflow-hidden">
            <div
              className="h-full bg-[var(--color-accent)] transition-all duration-300"
              style={{ width: `${uploadProgress}%` }}
            />
          </div>
        </div>
      ) : (
        <>
          <div className="w-12 h-12 mx-auto mb-3 text-[var(--color-text-tertiary)]">
            <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
              />
            </svg>
          </div>
          <p className="text-sm text-[var(--color-text-secondary)] mb-1">
            拖拽文件到此处或点击上传
          </p>
          <p className="text-xs text-[var(--color-text-tertiary)]">
            {type === 'live2d' ? '支持 .model.json/.model3.json/.zip/.moc3 文件' : '支持 .vrm 文件'}，最大 {effectiveMaxFileSizeMb}MB
          </p>
        </>
      )}
    </div>
  );
}

export default AvatarUploader;
