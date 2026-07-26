import { type SVGProps } from 'react';

/** 丝带～ 图标 */
export default function Ribbon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M4 4C4 4 8 8 12 8C16 8 20 4 20 4C20 4 18 8 18 12C18 16 20 20 20 20C20 20 16 16 12 16C8 16 4 20 4 20C4 20 6 16 6 12C6 8 4 4 4 4Z" />
    </svg>
  );
}
