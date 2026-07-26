import { type SVGProps } from 'react';

/** 权杖 图标 */
export default function Scepter(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M12 2L14 6L12 10L10 6L12 2ZM11 10V20H8V22H16V20H13V10C13 10 12 11 12 11S11 10 11 10ZM6 14C6 14 4 15 4 17C4 19 6 20 6 20C6 20 5 18 6 17C7 16 8 16 8 16L6 14ZM18 14L16 16C16 16 17 16 18 17C19 18 18 20 18 20C18 20 20 19 20 17C20 15 18 14 18 14Z" />
    </svg>
  );
}
