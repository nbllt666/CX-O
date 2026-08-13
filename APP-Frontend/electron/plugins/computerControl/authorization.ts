/**
 * SubTask 2.1 授权状态代理。
 *
 * 永久授权状态（authorized 布尔）的唯一读/写入口。渲染层不得直接执行本机控制，
 * 只能经主进程校验授权后调用工具；本代理即为该"主进程校验授权"的状态来源。
 *
 * 设计上不依赖 electron，持久化通过注入的 AuthorizationPersistence 完成，
 * 便于单测注入内存替身并断言无 OS 副作用。
 */
export interface AuthorizationPersistence {
  /** 读取持久化授权状态；文件不存在/损坏时返回 null */
  load(): boolean | null;
  /** 持久化授权状态 */
  save(value: boolean): void;
}

export class AuthorizationStore {
  private authorized: boolean;

  constructor(
    private readonly persistence: AuthorizationPersistence,
    defaultState = false,
  ) {
    const loaded = persistence.load();
    this.authorized = loaded === null ? defaultState : loaded;
  }

  isAuthorized(): boolean {
    return this.authorized;
  }

  /** 开启授权并持久化 */
  setAuthorized(value: boolean): void {
    this.authorized = value;
    this.persistence.save(value);
  }

  /** 撤销授权并持久化 */
  revoke(): void {
    this.setAuthorized(false);
  }
}
