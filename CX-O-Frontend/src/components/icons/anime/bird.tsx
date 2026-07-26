import { type SVGProps } from 'react';

/** 鸟 图标 */
export default function Bird(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M4 4C4 4 8 6 10 10C11 12 12 14 13 16C14 14 16 12 18 11C20 10 22 10 22 10C22 10 20 12 19 14C18 16 17 18 16 19C17 20 18 21 18 21H14C12 21 10 19 9 16C7 12 4 4 4 4Z" />
    </svg>
  );
}
