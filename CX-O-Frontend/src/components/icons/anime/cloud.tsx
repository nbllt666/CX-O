import { type SVGProps } from 'react';

/** 云朵 图标 */
export default function Cloud(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M6 19C3 19 1 17 1 14C1 11 3 9 6 9C6 5 9 2 13 2C17 2 20 5 20 9C22 9 23 11 23 13C23 16 21 19 18 19H6Z" />
    </svg>
  );
}
