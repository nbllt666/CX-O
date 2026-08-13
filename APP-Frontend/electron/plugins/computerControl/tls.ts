/**
 * SubTask 2.3 TLS 自签名证书生成、持久化与指纹计算。
 *
 * 使用 node-forge 纯 JS 生成 2048 位 RSA 自签名证书（serverAuth），并持久化到
 * 用户目录，避免每次启动重新生成导致客户端指纹漂移。指纹取证书 DER 的 SHA-256
 * 摘要，供客户端校验（防中间人），也通过 /health 暴露。
 *
 * 不依赖 electron，可纯 node 单测。
 */
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as forge from 'node-forge';

export interface TlsMaterial {
  cert: string;
  key: string;
  /** 形如 AA:BB:... 的 SHA-256 指纹 */
  fingerprint: string;
  certPath: string;
  keyPath: string;
}

export function computeFingerprint(certPem: string): string {
  const cert = forge.pki.certificateFromPem(certPem);
  const der = forge.asn1.toDer(forge.pki.certificateToAsn1(cert)).getBytes();
  const md = forge.md.sha256.create();
  md.update(der);
  return md.digest().toHex().toUpperCase().replace(/(.{2})(?=.)/g, '$1:');
}

export function generateSelfSignedCertificate(opts: {
  commonName?: string;
  days?: number;
} = {}): { cert: string; key: string } {
  const keys = forge.pki.rsa.generateKeyPair(2048);
  const cert = forge.pki.createCertificate();
  cert.publicKey = keys.publicKey;
  cert.serialNumber = '01' + Date.now().toString(16).toUpperCase();
  cert.validity.notBefore = new Date();
  cert.validity.notAfter = new Date(Date.now() + (opts.days ?? 3650) * 86_400_000);

  const attrs = [
    { name: 'commonName', value: opts.commonName ?? 'cxo-pet-computer-control' },
    { name: 'organizationName', value: 'CXO-Pet' },
  ];
  cert.setSubject(attrs);
  cert.setIssuer(attrs);
  cert.setExtensions([
    { name: 'basicConstraints', cA: false },
    { name: 'keyUsage', digitalSignature: true, keyEncipherment: true, keyCertSign: false },
    { name: 'extKeyUsage', serverAuth: true },
    {
      name: 'subjectAltName',
      altNames: [
        { type: 2, value: 'localhost' },
        { type: 7, ip: '127.0.0.1' },
      ],
    },
  ]);
  cert.sign(keys.privateKey, forge.md.sha256.create());

  return {
    cert: forge.pki.certificateToPem(cert),
    key: forge.pki.privateKeyToPem(keys.privateKey),
  };
}

/**
 * 从磁盘加载证书，缺失则生成并写入（私钥文件权限 0600）。
 * 重复调用幂等：优先复用已有证书，保证指纹稳定。
 */
export function ensureCertificate(certDir: string): TlsMaterial {
  fs.mkdirSync(certDir, { recursive: true });
  const certPath = path.join(certDir, 'server.crt');
  const keyPath = path.join(certDir, 'server.key');

  if (fs.existsSync(certPath) && fs.existsSync(keyPath)) {
    const cert = fs.readFileSync(certPath, 'utf-8');
    const key = fs.readFileSync(keyPath, 'utf-8');
    return { cert, key, fingerprint: computeFingerprint(cert), certPath, keyPath };
  }

  const { cert, key } = generateSelfSignedCertificate();
  fs.writeFileSync(certPath, cert, { encoding: 'utf-8' });
  fs.writeFileSync(keyPath, key, { encoding: 'utf-8', mode: 0o600 });
  return { cert, key, fingerprint: computeFingerprint(cert), certPath, keyPath };
}
