/**
 * discovery 域客户端：局域网后端自动发现。
 *
 * 调用当前后端 /api/discovery/backends，由服务端扫描本机所在子网并返回可达的
 * CX-O 后端地址列表，前端据此一键切换后端，避免手动填写 IP 端口。
 */
import { request } from '../base';

export interface DiscoveredBackend {
  url: string;
  host: string;
  port: number;
}

export interface DiscoverBackendsResult {
  backends: DiscoveredBackend[];
}

export const discoveryApi = {
  /** 自动发现局域网内的 CX-O 后端；port 取当前生效后端端口，扫描与之同口 */
  discover(port: number): Promise<DiscoverBackendsResult> {
    return request<DiscoverBackendsResult>({
      url: '/api/discovery/backends',
      params: { port },
    });
  },
};
