import { type SVGProps } from 'react';

/** 翅膀 图标 */
export default function Wing(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M12 4C12 4 8 6 5 10C3 13 2 17 2 20C2 20 6 19 9 16C8 18 7 20 7 20C7 20 11 18 14 14C16 11 17 7 17 4C17 4 14 5 12 4ZM12 4C12 4 16 6 19 10C21 13 22 17 22 20C22 20 18 19 15 16C16 18 17 20 17 20C17 20 13 18 10 14C8 11 7 7 7 4C7 4 10 5 12 4Z" />
    </svg>
  );
}
