import { type SVGProps } from 'react';

/** 气泡 图标 */
export default function Bubble(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M12 2C6 2 2 6 2 12C2 18 6 22 12 22C18 22 22 18 22 12C22 6 18 2 12 2ZM12 4C17 4 20 7 20 12C20 17 17 20 12 20C7 20 4 17 4 12C4 7 7 4 12 4ZM9 9C9 10 8 11 7 11C6 11 5 10 5 9C5 8 6 7 7 7C8 7 9 8 9 9Z" />
    </svg>
  );
}
