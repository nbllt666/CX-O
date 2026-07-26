import { type SVGProps } from 'react';

/** 玫瑰 图标 */
export default function Rose(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M12 2C14 2 16 4 16 6C16 7 15.5 8 15 8.5C16 8 17 7.5 18 8C20 9 21 11 20 13C19 15 17 16 15 15C16 16 16 17 16 18C16 20 14 22 12 22C10 22 8 20 8 18C8 17 8 16 9 15C7 16 5 15 4 13C3 11 4 9 6 8C7 7.5 8 8 9 8.5C8.5 8 8 7 8 6C8 4 10 2 12 2ZM12 10C11 10 10 11 10 12C10 13 11 14 12 14C13 14 14 13 14 12C14 11 13 10 12 10Z" />
    </svg>
  );
}
