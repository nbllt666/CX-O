import { type SVGProps } from 'react';

/** 龙 图标 */
export default function Dragon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M6 4C6 4 8 6 10 6C12 6 14 4 16 4C19 4 21 7 21 10C21 13 19 16 16 16C15 16 14 15.5 13 15C14 16 15 17 15 18C15 19 14 20 12 20C9 20 6 18 5 15C4 12 4 8 6 4ZM16 9C16.5 9 17 9.5 17 10C17 10.5 16.5 11 16 11C15.5 11 15 10.5 15 10C15 9.5 15.5 9 16 9Z" />
    </svg>
  );
}
