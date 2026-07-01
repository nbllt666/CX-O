/**
 * API Client — unified facade for all backend API calls.
 *
 * Refactored in M16: implementation split into domain mixins under ./clients/.
 * This file re-exports the public API surface for backward compatibility.
 * Import paths from `@/api/client` remain unchanged.
 */

// Base class
import { _ApiClientBase } from './clients/_common';

// Domain mixins
import { _HealthClientMixin } from './clients/health';
import { _ChatClientMixin } from './clients/chat';
import { _AgentsClientMixin } from './clients/agents';
import { _MemoriesClientMixin } from './clients/memories';
import { _ToolsClientMixin } from './clients/tools';
import { _VectorClientMixin } from './clients/vector';
import { _GraphClientMixin } from './clients/graph';
import { _AudioClientMixin } from './clients/audio';
import { _AvatarsClientMixin } from './clients/avatars';
import { _CxfcClientMixin } from './clients/cxfc';
import { _ServiceClientMixin } from './clients/service';
import { _ConfigClientMixin } from './clients/config';

// Re-export URL utilities (originally exported from this module)
export {
  getApiBaseUrl,
  getControlServiceUrl,
  getWsBaseUrl,
  getVoiceWorkstationUrl,
  getWS_BASE_URL,
  httpToWsUrl,
  setCachedBackendUrl,
  setCachedWsUrl,
  initBackendUrl,
  getApiUrl,
  getControlUrl,
  getVoiceWorkstationUrlFn,
} from './clients/_common';

// Re-export all public interface types
export type {
  Agent,
  HealthStatus,
  GraphStats,
  AcpStats,
  AcpAgentRow,
  ArchiveStats,
  ToolStats,
  Tool,
  CxfcPlugin,
  CxfcSkill,
  CxfcDiscoveredPlugin,
  FrontendLimits,
  GraphEntity,
  GraphRelation,
  VectorData,
  DuplicateGroup,
  ArchiveResult,
  Memory,
  Session,
  ChatMessage,
} from './clients/_types';

// Compose ApiClient: base class + all domain mixins via applyMixins pattern
class ApiClient extends _ApiClientBase {}

// Declaration merging: tell TypeScript that ApiClient has all mixin methods
interface ApiClient
  extends _HealthClientMixin,
    _ChatClientMixin,
    _AgentsClientMixin,
    _MemoriesClientMixin,
    _ToolsClientMixin,
    _VectorClientMixin,
    _GraphClientMixin,
    _AudioClientMixin,
    _AvatarsClientMixin,
    _CxfcClientMixin,
    _ServiceClientMixin,
    _ConfigClientMixin {}

// Copy methods from mixin classes to ApiClient prototype
applyMixins(ApiClient, [
  _HealthClientMixin,
  _ChatClientMixin,
  _AgentsClientMixin,
  _MemoriesClientMixin,
  _ToolsClientMixin,
  _VectorClientMixin,
  _GraphClientMixin,
  _AudioClientMixin,
  _AvatarsClientMixin,
  _CxfcClientMixin,
  _ServiceClientMixin,
  _ConfigClientMixin,
]);

export const api = new ApiClient();

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function applyMixins(derivedCtor: any, baseCtors: any[]) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  baseCtors.forEach((baseCtor: any) => {
    Object.getOwnPropertyNames(baseCtor.prototype).forEach((name: string) => {
      if (name !== 'constructor') {
        Object.defineProperty(
          derivedCtor.prototype,
          name,
          Object.getOwnPropertyDescriptor(baseCtor.prototype, name) || Object.create(null)
        );
      }
    });
  });
}
