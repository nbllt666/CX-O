import { type SVGProps } from 'react';

/** 蝴蝶 图标 */
export default function Butterfly(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M12 6C12 6 10 2 6 2C3 2 2 5 2 8C2 12 5 14 8 14C10 14 12 12 12 10C12 12 14 14 16 14C19 14 22 12 22 8C22 5 21 2 18 2C14 2 12 6 12 6ZM11 8C11 8 11 12 11 14C11 17 12 20 12 20C12 20 13 17 13 14C13 12 13 8 13 8C13 8 12 8 11 8Z" />
    </svg>
  );
}
