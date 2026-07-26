import { type SVGProps } from 'react';

/** 闪烁 图标 */
export default function Sparkle(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M12 2L13 9L20 10L13 11L12 18L11 11L4 10L11 9L12 2ZM19 16L19.5 19L22 19.5L19.5 20L19 23L18.5 20L16 19.5L18.5 19L19 16Z" />
    </svg>
  );
}
