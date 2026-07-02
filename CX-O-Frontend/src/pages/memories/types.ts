export interface Memory {
  id: number;
  content: string;
  type: string;
  importance: number;
  tags: string[];
  created_at: string;
  is_archived: boolean;
  emotion_score?: number;
}

export type ViewMode = 'card' | 'list';

export const typeLabels: Record<string, string> = {
  permanent: '永久',
  long_term: '长期',
  short_term: '短期',
};
