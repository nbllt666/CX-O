import { type SVGProps } from 'react';

/** 皇冠 图标 */
export default function Crown(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M2 18L4 7L9 12L12 5L15 12L20 7L22 18H2ZM2 19H22V21H2V19Z" />
    </svg>
  );
}
