import { app } from 'electron';
import * as fs from 'node:fs';
import * as path from 'node:path';

function getConfigPath(): string {
  return path.join(app.getPath('userData'), 'config.json');
}

function readConfig(): Record<string, string> {
  const configPath = getConfigPath();
  try {
    const data = fs.readFileSync(configPath, 'utf-8');
    return JSON.parse(data);
  } catch (error: unknown) {
    if ((error as { code?: string }).code === 'ENOENT') {
      return {};
    }
    throw error;
  }
}

function writeConfig(config: Record<string, string>): void {
  const configPath = getConfigPath();
  fs.writeFileSync(configPath, JSON.stringify(config, null, 2), 'utf-8');
}

export function getConfig(key: string): string | null {
  const config = readConfig();
  return config[key] ?? null;
}

export function setConfig(key: string, value: string): void {
  const config = readConfig();
  config[key] = value;
  writeConfig(config);
}
