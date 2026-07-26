import type { ElementType } from 'react';
import { Card } from '@/components/ui-v2';

interface StatCardProps {
  title: string;
  value: number;
  icon: ElementType;
  loading?: boolean;
  trend?: string;
}

export function StatCard({ title, value, icon: Icon, loading, trend }: StatCardProps) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-muted-foreground">{title}</p>
          {loading ? (
            <div className="h-8 w-16 bg-muted rounded animate-pulse mt-1" />
          ) : (
            <div className="flex items-baseline gap-2">
              <p className="text-2xl font-bold">{value}</p>
              {trend && <span className="text-xs text-green-500">{trend}</span>}
            </div>
          )}
        </div>
        <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
          <Icon className="w-5 h-5 text-primary" />
        </div>
      </div>
    </Card>
  );
}
