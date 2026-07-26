import { type SVGProps } from 'react';

/** 宝石 图标 */
export default function Gem(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M6 2H18L23 9L12 22L1 9L6 2ZM7 4L3 9L11 19V11H7V4ZM17 4V11H13V19L21 9L17 4Z" />
    </svg>
  );
}
