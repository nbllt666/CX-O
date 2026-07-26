import { type SVGProps } from 'react';

/** 彩虹 图标 */
export default function Rainbow(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M2 18C2 10 8 4 12 4C16 4 22 10 22 18" />
      <path d="M5 18C5 12 9 7 12 7C15 7 19 12 19 18" />
      <path d="M8 18C8 14 10 10 12 10C14 10 16 14 16 18" />
      <path d="M11 18C11 15 11 13 12 13C13 13 13 15 13 18" />
    </svg>
  );
}
