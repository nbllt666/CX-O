import { type SVGProps } from 'react';

/** 樱花 图标 */
export default function Sakura(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M12 2C12 2 13 6 15 7C17 8 20 7 20 7C20 7 18 10 18 12C18 14 20 17 20 17C20 17 17 16 15 17C13 18 12 22 12 22C12 22 11 18 9 17C7 16 4 17 4 17C4 17 6 14 6 12C6 10 4 7 4 7C4 7 7 8 9 7C11 6 12 2 12 2Z" />
    </svg>
  );
}
