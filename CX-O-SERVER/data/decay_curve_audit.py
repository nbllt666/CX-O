"""衰减曲线审计：六档分层设计的声明目标 vs 实际参数曲线。一次性脚本。"""
import math

LEVELS = [
    # (档位, 类型, importance_score, alpha, lambda1, lambda2, 声明 retention_180d)
    ("imp>=0.95 (5分/permanent)", "zero", 1.0, 0.0, 0.0, 0.0, 1.0),
    ("0.85-0.99 (imp 4.3-5)", "exp", 0.92, 0.20, 0.01, 0.001, 0.95),
    ("0.70-0.84 (imp 3.5-4.2)", "exp", 0.77, 0.35, 0.08, 0.015, 0.80),
    ("0.50-0.69 (imp 2.5-3.4)", "exp", 0.60, 0.60, 0.25, 0.04, 0.50),
    ("0.30-0.49 (imp 1.5-2.4)", "exp", 0.40, 0.75, 0.45, 0.08, 0.25),
    ("0.00-0.29 (imp 0-1.4)", "exp", 0.15, 0.90, 0.80, 0.15, 0.05),
]


def factor(alpha: float, l1: float, l2: float, t: float) -> float:
    return alpha * math.exp(-l1 * t) + (1 - alpha) * math.exp(-l2 * t)


def main() -> None:
    hdr = f"{'档位':<24}{'声明180d':>9}{'实际180d':>9}{'实际30d':>9}{'实际365d':>9}{'实际3yr':>9}"
    print(hdr)
    print("-" * len(hdr))
    for name, typ, _s, alpha, l1, l2, declared in LEVELS:
        if typ == "zero":
            print(f"{name:<24}{declared:>9.2f}{1.0:>9.2f}{1.0:>9.2f}{1.0:>9.2f}{1.0:>9.2f}")
            continue
        print(
            f"{name:<24}{declared:>9.2f}"
            f"{factor(alpha, l1, l2, 180):>9.3f}"
            f"{factor(alpha, l1, l2, 30):>9.3f}"
            f"{factor(alpha, l1, l2, 365):>9.3f}"
            f"{factor(alpha, l1, l2, 1095):>9.3f}"
        )
    print()
    print("反解参数（保留声明 retention_180d 目标，快相 7 天内完成，慢相由 180d 目标反解 lambda2）:")
    for name, typ, _s, alpha, l1, _l2, declared in LEVELS:
        if typ == "zero":
            continue
        l2n = -math.log(declared / (1 - alpha)) / 180
        v180 = factor(alpha, l1, l2n, 180)
        v30 = factor(alpha, l1, l2n, 30)
        v3y = factor(alpha, l1, l2n, 1095)
        print(
            f"{name:<24} lambda2 {_l2} -> {l2n:.5f}"
            f"  [180d={v180:.3f} 30d={v30:.3f} 365d={factor(alpha, l1, l2n, 365):.3f} 3yr={v3y:.3f}]"
        )


if __name__ == "__main__":
    main()
