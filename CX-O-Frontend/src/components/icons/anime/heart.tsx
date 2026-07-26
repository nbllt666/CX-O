import { type SVGProps } from 'react';

/** 爱心 图标 */
export default function Heart(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M12 21S4 14 4 8.5C4 5.5 6.5 3 9.5 3C11 3 12 4 12 4S13 3 14.5 3C17.5 3 20 5.5 20 8.5C20 14 12 21 12 21Z" />
    </svg>
  );
}
