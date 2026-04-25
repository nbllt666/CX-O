import React, { useEffect, useRef } from 'react';
import { useMotionValue, useTransform, animate } from 'framer-motion';

interface CountUpProps {
  end: number;
  duration?: number;
  prefix?: string;
  suffix?: string;
  className?: string;
}

export const CountUp: React.FC<CountUpProps> = ({
  end,
  duration = 1000,
  prefix = '',
  suffix = '',
  className,
}) => {
  const count = useMotionValue(0);
  const rounded = useTransform(count, (latest) => Math.round(latest));
  const displayValue = useRef(0);

  useEffect(() => {
    const controls = animate(count, end, {
      duration: duration / 1000,
      ease: 'easeOut',
    });

    const unsubscribe = rounded.on('change', (latest) => {
      displayValue.current = latest;
    });

    return () => {
      controls.stop();
      unsubscribe();
    };
  }, [count, end, duration, rounded]);

  return (
    <span className={className}>
      {prefix}
      {displayValue.current}
      {suffix}
    </span>
  );
};
