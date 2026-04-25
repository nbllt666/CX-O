import React from 'react';
import { motion, Variants } from 'framer-motion';

interface AnimatedListProps {
  children: React.ReactNode;
  className?: string;
  staggerDelay?: number;
  direction?: 'up' | 'down' | 'left' | 'right';
}

const getDirectionOffset = (direction: 'up' | 'down' | 'left' | 'right') => {
  const offset = 20;
  switch (direction) {
    case 'up':
      return { x: 0, y: offset };
    case 'down':
      return { x: 0, y: -offset };
    case 'left':
      return { x: offset, y: 0 };
    case 'right':
      return { x: -offset, y: 0 };
    default:
      return { x: 0, y: offset };
  }
};

export const AnimatedList: React.FC<AnimatedListProps> = ({
  children,
  className,
  staggerDelay = 50,
  direction = 'up',
}) => {
  const offset = getDirectionOffset(direction);

  const containerVariants: Variants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: {
        staggerChildren: staggerDelay / 1000,
        when: 'beforeChildren',
      },
    },
  };

  const itemVariants: Variants = {
    hidden: {
      opacity: 0,
      x: offset.x,
      y: offset.y,
    },
    visible: {
      opacity: 1,
      x: 0,
      y: 0,
      transition: {
        duration: 0.3,
        ease: 'easeOut',
      },
    },
  };

  return (
    <motion.div
      className={className}
      variants={containerVariants}
      initial="hidden"
      animate="visible"
    >
      {React.Children.map(children, (child, index) => (
        <motion.div key={index} variants={itemVariants}>
          {child}
        </motion.div>
      ))}
    </motion.div>
  );
};

export default AnimatedList;
