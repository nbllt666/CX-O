import { type SVGProps } from 'react';

/** 流星 图标 */
export default function ShootingStar(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M15 3L17 9L23 11L17 13L15 19L13 13L7 11L13 9L15 3ZM5 15L6 18L9 19L6 20L5 23L4 20L1 19L4 18L5 15Z" />
    </svg>
  );
}
