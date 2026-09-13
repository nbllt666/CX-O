/**
 * VRM 骨骼 PID 平滑控制器（单轴）。
 *
 * 背景：vrmEngine.ts 的 boneControl 路径原为简单指数 lerp（`current += (target-current)*factor`），
 * 大角度突变时表现生硬。本模块以 PID 控制器替代：
 * - P（比例）主导：误差越大响应越快，一阶指数式趋近，无内在超调；
 * - I（积分）小值抗静差：消除收敛尾段的残余误差。带两重 anti-windup：
 *   ① clamping——输出饱和且积分继续推高时停止累积；
 *   ② 积分分离——|误差| 超过 integralSeparation 时暂停累积（大误差段 P 主导即可，
 *     防止积分膨胀引发超调与极限环；小误差段 I 恢复补偿静差）；
 * - D（微分）抑制超调：采用「微分先行」（对测量值差分而非误差差分），
 *   目标突变时不产生微分冲击，仅在速度过大时提供反向阻尼。
 *
 * 稳定性保障（默认参数在全帧率 1/120s~0.1s 下无振荡、无超调）：
 * - 输出为角速度指令，受 maxSpeed 限幅；
 * - 单帧 dt 超过 maxDt 时钳制（防切后台回来积分爆炸与位置跳变）；
 * - dt <= 0 或非有限值时不推进，保持 current 不变且不产生 NaN；
 * - 残差小于 epsilon 时直接归位目标（与引擎 easeTowards 的残差归位口径一致）。
 *
 * 每根骨骼的 x/y/z 三轴各持有一个独立实例（见 vrmEngine.ts boneControl 路径）。
 */

/** PID 可配参数（全部带默认值，经单一 options 对象注入） */
export interface BonePidOptions {
  /** 比例增益（主导项）：误差 1rad 对应 kp rad/s 的速度指令，默认 6.0 */
  kp?: number;
  /** 积分增益（小值抗静差），默认 0.8 */
  ki?: number;
  /** 微分增益（抑制超调，微分先行），默认 0.3 */
  kd?: number;
  /** 积分限幅（rad·s，anti-windup 钳制上限），默认 0.5 */
  integralLimit?: number;
  /**
   * 积分分离阈值（rad）：|误差| 大于该值时暂停积分累积（大误差段 P 主导，
   * 防 windup 与 I 驱动极限环；小误差段 I 恢复补偿静差），默认 0.05
   */
  integralSeparation?: number;
  /** 最大角速度限幅（rad/s），默认 10 */
  maxSpeed?: number;
  /** 单帧 dt 钳制上限（s），防切后台/长帧跳变，默认 0.5 */
  maxDt?: number;
  /** 收敛阈值（rad）：|误差| 小于该值直接归位目标，默认 0.0005 */
  epsilon?: number;
}

/** 默认参数：P 主导、小 I（积分分离）、小 D，保证阶跃响应平滑无振荡 */
const PID_DEFAULTS = {
  kp: 6.0,
  ki: 0.8,
  kd: 0.3,
  integralLimit: 0.5,
  integralSeparation: 0.05,
  maxSpeed: 10,
  maxDt: 0.5,
  epsilon: 0.0005,
} as const;

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export class BonePidController {
  /** 当前角度（rad），PID 状态的核心输出 */
  private current: number;
  /** 目标角度（rad） */
  private target: number;
  /** 积分器状态（误差×时间累积，anti-windup 钳制） */
  private integral = 0;
  /** 上一帧角度（微分先行差分用） */
  private lastCurrent: number;

  private readonly kp: number;
  private readonly ki: number;
  private readonly kd: number;
  private readonly integralLimit: number;
  private readonly integralSeparation: number;
  private readonly maxSpeed: number;
  private readonly maxDt: number;
  private readonly epsilon: number;

  /**
   * @param initial 初始角度（与骨骼当前 rotation 同步，避免首帧跳变）
   * @param options 可配参数，缺省用稳定默认值
   */
  constructor(initial = 0, options: BonePidOptions = {}) {
    this.kp = options.kp ?? PID_DEFAULTS.kp;
    this.ki = options.ki ?? PID_DEFAULTS.ki;
    this.kd = options.kd ?? PID_DEFAULTS.kd;
    this.integralLimit = options.integralLimit ?? PID_DEFAULTS.integralLimit;
    this.integralSeparation =
      options.integralSeparation ?? PID_DEFAULTS.integralSeparation;
    this.maxSpeed = options.maxSpeed ?? PID_DEFAULTS.maxSpeed;
    this.maxDt = options.maxDt ?? PID_DEFAULTS.maxDt;
    this.epsilon = options.epsilon ?? PID_DEFAULTS.epsilon;

    this.current = Number.isFinite(initial) ? initial : 0;
    this.target = this.current;
    this.lastCurrent = this.current;
  }

  /** 写入新目标角度；非有限值时忽略（保持原目标，防御上游脏数据） */
  setTarget(target: number): void {
    if (Number.isFinite(target)) {
      this.target = target;
    }
  }

  /**
   * 推进一帧，返回新的当前角度。
   *
   * @param dt 帧间隔（s）；<=0 或非有限值时不推进
   * @param gainScale 外部响应度倍率（对齐骨骼 speed 语义：1.0 常规 / 3.3 归中加速），
   *                  仅缩放比例项，缺省 1
   */
  update(dt: number, gainScale = 1): number {
    // dt 安全防护：非有限值或 <=0 时不推进，保持 current 不变且不产生 NaN
    if (!Number.isFinite(dt) || dt <= 0) {
      return this.current;
    }
    const step = Math.min(dt, this.maxDt);
    const error = this.target - this.current;

    // 收敛归位：残差小于阈值直接贴合目标，并清空积分/微分历史
    if (Math.abs(error) <= this.epsilon) {
      this.current = this.target;
      this.integral = 0;
      this.lastCurrent = this.target;
      return this.current;
    }

    // P 项（主导）：gainScale 缩放响应度
    const scale = Number.isFinite(gainScale) && gainScale > 0 ? gainScale : 1;
    const p = this.kp * scale * error;
    // D 项（微分先行）：对测量值差分，目标突变不产生冲击，速度越大阻尼越强
    const d = -this.kd * ((this.current - this.lastCurrent) / step);
    const base = p + d;

    // I 项（小值抗静差）+ 双重 anti-windup：
    // ① clamping——输出已饱和且积分极性与误差同向（会继续推高饱和）时，本帧停止累积；
    // ② 积分分离——误差大于阈值时暂停累积（大误差段 P 主导足够）
    const raw = base + this.ki * this.integral;
    const saturated = Math.abs(raw) >= this.maxSpeed;
    const samePolarity = Math.sign(raw) === Math.sign(error);
    const allowIntegrate =
      !(saturated && samePolarity) && Math.abs(error) <= this.integralSeparation;
    if (allowIntegrate) {
      this.integral = clamp(this.integral + error * step, -this.integralLimit, this.integralLimit);
    }

    // 速度指令限幅后积分位移（保证大误差下单帧位移可控，不跳变）
    const velocity = clamp(base + this.ki * this.integral, -this.maxSpeed, this.maxSpeed);
    this.lastCurrent = this.current;
    this.current += velocity * step;
    return this.current;
  }

  /**
   * 重置控制器状态：清空积分/微分历史。
   * @param current 省略时保留当前角度（用于归中/释放时清历史而保持运动连续）；
   *                传入时把当前角度设为该值（用于测试或重新初始化）
   */
  reset(current?: number): void {
    if (current !== undefined && Number.isFinite(current)) {
      this.current = current;
    }
    this.integral = 0;
    this.lastCurrent = this.current;
  }

  /** 当前角度（供测试/调试读取） */
  get value(): number {
    return this.current;
  }
}
