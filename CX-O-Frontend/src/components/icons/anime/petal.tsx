import { type SVGProps } from 'react';

/** 花瓣❀ 图标 */
export default function Petal(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M12 2C12 6 8 9 2 9C8 9 12 12 12 22C12 18 16 15 22 15C16 15 12 12 12 2Z" />
    </svg>
  );
}
