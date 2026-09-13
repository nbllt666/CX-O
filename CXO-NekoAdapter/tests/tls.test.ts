// @vitest-environment node
/**
 * TLS 自签名证书单测（tests/tls.test.ts）
 * ============================================================================
 * 覆盖 src/shared/tls.ts（迁移自 APP-Frontend electron/plugins/computerControl/tls.ts）：
 *  - ensureCertificate 首次生成：cert/key/fingerprint 齐全并写入磁盘，
 *    fingerprint 为 SHA-256 十六进制冒号分隔格式（32 组两位大写十六进制）；
 *  - 二次调用幂等复用：证书内容与 mtime 不变、指纹稳定（客户端不漂移）；
 *  - 缓存不完整（缺 key 文件）时重建缺失文件；
 *  - 缓存内容损坏（非 PEM）时的当前行为：计算指纹抛错（实现无损坏重建逻辑，
 *    属已知 src 缺陷，此处锁定现状防回归，待修复后改为断言重建）；
 *  - computeFingerprint 对同一证书稳定、不同证书不同。
 *
 * 证书目录使用 os.tmpdir 下 mkdtemp 临时目录，绝不读写真实 data/certs。
 * ============================================================================
 */
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import * as forge from 'node-forge';
import { computeFingerprint, ensureCertificate, generateSelfSignedCertificate } from '../src/shared/tls';

/** 本轮用例的临时证书目录 */
let certDir: string;

beforeEach(() => {
  certDir = fs.mkdtempSync(path.join(os.tmpdir(), 'cxo-tls-test-'));
});

afterEach(() => {
  fs.rmSync(certDir, { recursive: true, force: true });
});

describe('ensureCertificate 首次生成', () => {
  it('cert/key/fingerprint 齐全并写入磁盘，指纹为 SHA-256 十六进制冒号分隔', () => {
    const m = ensureCertificate(certDir);
    expect(m.cert).toContain('BEGIN CERTIFICATE');
    expect(m.key).toContain('PRIVATE KEY');
    expect(m.certPath).toBe(path.join(certDir, 'server.crt'));
    expect(m.keyPath).toBe(path.join(certDir, 'server.key'));
    expect(fs.existsSync(m.certPath)).toBe(true);
    expect(fs.existsSync(m.keyPath)).toBe(true);
    // SHA-256 → 32 字节 → 32 组两位大写十六进制、冒号分隔（如 AA:BB:...）
    expect(m.fingerprint).toMatch(/^[0-9A-F]{2}(:[0-9A-F]{2}){31}$/);
    // 指纹与证书内容自洽
    expect(m.fingerprint).toBe(computeFingerprint(m.cert));
    // 私钥文件权限 0600（POSIX 语义；Windows 平台不保留 POSIX 权限位，跳过）
    if (process.platform !== 'win32') {
      expect(fs.statSync(m.keyPath).mode & 0o777).toBe(0o600);
    }
  });

  it('目录不存在时自动创建（recursive mkdir）', () => {
    const nested = path.join(certDir, 'a', 'b', 'certs');
    const m = ensureCertificate(nested);
    expect(fs.existsSync(m.certPath)).toBe(true);
    expect(fs.existsSync(m.keyPath)).toBe(true);
  });
});

describe('ensureCertificate 复用（幂等，指纹稳定）', () => {
  it('二次调用复用已有证书：内容与 mtime 不变、指纹一致', () => {
    const first = ensureCertificate(certDir);
    const mtimeCert = fs.statSync(first.certPath).mtimeMs;
    const mtimeKey = fs.statSync(first.keyPath).mtimeMs;

    const second = ensureCertificate(certDir);
    expect(second.cert).toBe(first.cert); // 未重新生成
    expect(second.key).toBe(first.key);
    expect(second.fingerprint).toBe(first.fingerprint); // 客户端指纹不漂移
    expect(fs.statSync(second.certPath).mtimeMs).toBe(mtimeCert); // 未重写文件
    expect(fs.statSync(second.keyPath).mtimeMs).toBe(mtimeKey);
  });

  it('缓存不完整（缺 key 文件）时重建缺失文件并重签证书', () => {
    const first = ensureCertificate(certDir);
    fs.rmSync(first.keyPath); // 只删私钥，模拟不完整缓存
    const second = ensureCertificate(certDir);
    expect(fs.existsSync(second.keyPath)).toBe(true);
    expect(second.key).not.toBe(first.key); // 新私钥
    expect(second.cert).not.toBe(first.cert); // 证书随新密钥重签
    expect(second.fingerprint).not.toBe(first.fingerprint);
  });
});

describe('缓存内容损坏（缺陷锁定）', () => {
  it('缓存文件存在但内容损坏（非 PEM）时：当前实现计算指纹抛错而非重建（已知 src 缺陷，锁定现状防回归）', () => {
    fs.writeFileSync(path.join(certDir, 'server.crt'), 'not-a-valid-pem', 'utf-8');
    fs.writeFileSync(path.join(certDir, 'server.key'), 'not-a-valid-key', 'utf-8');
    // ensureCertificate 命中"两文件都在"分支后 computeFingerprint 解析 PEM 失败抛错；
    // 实现缺少"损坏即重建"容错，修复后应改断言为重建成功且文件内容为合法 PEM。
    expect(() => ensureCertificate(certDir)).toThrow();
  });
});

describe('computeFingerprint / generateSelfSignedCertificate', () => {
  it('同一证书指纹计算稳定，不同证书指纹不同', () => {
    const a = generateSelfSignedCertificate();
    expect(computeFingerprint(a.cert)).toBe(computeFingerprint(a.cert));
    const b = generateSelfSignedCertificate();
    expect(computeFingerprint(b.cert)).not.toBe(computeFingerprint(a.cert));
  });

  it('生成证书携带默认 CN 与 serverAuth 扩展（PEM 结构完整，SAN 含 localhost/127.0.0.1）', () => {
    const { cert, key } = generateSelfSignedCertificate({ commonName: 'cxo-test' });
    expect(cert).toContain('BEGIN CERTIFICATE');
    expect(key).toContain('PRIVATE KEY');
    // SAN 在 PEM 中是 DER 编码，须解析证书后断言（客户端校验依赖 localhost 与 127.0.0.1）
    const parsed = forge.pki.certificateFromPem(cert);
    expect(parsed.subject.getField('CN')?.value).toBe('cxo-test');
    const san = parsed.getExtension('subjectAltName');
    expect(san).toBeDefined();
    const altNames = (san?.altNames ?? []) as Array<{ type: number; value?: string; ip?: string }>;
    expect(altNames).toContainEqual(expect.objectContaining({ type: 2, value: 'localhost' }));
    expect(altNames).toContainEqual(expect.objectContaining({ type: 7, ip: '127.0.0.1' }));
    // extKeyUsage 含 serverAuth
    const eku = parsed.getExtension('extKeyUsage');
    expect(eku?.serverAuth).toBe(true);
  });
});
