import { type SVGProps } from 'react';

/** 鱼 图标 */
export default function Fish(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M2 12C2 12 6 6 12 6C16 6 19 9 20 12C19 15 16 18 12 18C6 18 2 12 2 12ZM20 10C20 10 22 8 22 6C22 6 21 10 21 12C21 14 22 18 22 18C22 16 20 14 20 14V10ZM16 11C16 11 15 10 14 10C13 10 12 11 12 12C12 13 13 14 14 14C15 14 16 13 16 12V11Z" />
    </svg>
  );
}
