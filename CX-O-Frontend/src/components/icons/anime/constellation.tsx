import { type SVGProps } from 'react';

/** 星座 图标 */
export default function Constellation(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M4 6L9 4L14 8L20 5L18 12L21 18L14 16L8 20L6 13L2 10L4 6Z" />
      <circle cx="4" cy="6" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="9" cy="4" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="14" cy="8" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="20" cy="5" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="18" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="21" cy="18" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="14" cy="16" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="8" cy="20" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="6" cy="13" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  );
}
