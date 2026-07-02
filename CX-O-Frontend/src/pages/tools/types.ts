import type { ElementType } from 'react';
import {
  Terminal,
  Globe,
  Database,
  FileText,
  Code,
  Wrench,
  Settings,
} from 'lucide-react';

export interface Tool {
  id: string;
  name: string;
  description: string;
  type: 'builtin' | 'mcp' | 'custom' | 'cxfc';
  status: 'active' | 'inactive' | 'error';
  config: Record<string, unknown>;
  icon?: string;
  created_at: string;
  last_used?: string;
  use_count: number;
  parameters?: Record<string, unknown>;
  examples?: string[];
  tags?: string[];
  source_plugin_id?: string;
}

export const toolIcons: Record<string, ElementType> = {
  terminal: Terminal,
  globe: Globe,
  database: Database,
  file: FileText,
  code: Code,
  wrench: Wrench,
  settings: Settings,
};

export const toolFallbackIcon = Wrench;

export const toolTemplates = {
  custom: {
    name: '',
    description: '',
    parameters: {
      type: 'object',
      properties: {},
      required: [],
    },
    examples: [],
  },
  mcp: {
    name: '',
    description: 'MCP 服务器工具',
    parameters: {
      type: 'object',
      properties: {
        server_name: {
          type: 'string',
          description: 'MCP 服务器名称',
        },
      },
      required: ['server_name'],
    },
    config: {
      server_name: '',
      tool_name: '',
    },
  },
  calculator: {
    name: 'calculator',
    description: '数学计算工具，支持基本运算、三角函数、对数等',
    parameters: {
      type: 'object',
      properties: {
        expression: {
          type: 'string',
          description: '数学表达式，如 "1 + 2" 或 "sin(30)"',
        },
      },
      required: ['expression'],
    },
    examples: ['1 + 2', 'sin(30)', 'log(100)'],
  },
  datetime: {
    name: 'datetime',
    description: '获取当前日期和时间',
    parameters: {
      type: 'object',
      properties: {
        format: {
          type: 'string',
          description: '日期格式，如 "YYYY-MM-DD HH:mm:ss"',
        },
      },
      required: [],
    },
    examples: ['', 'YYYY-MM-DD'],
  },
};
