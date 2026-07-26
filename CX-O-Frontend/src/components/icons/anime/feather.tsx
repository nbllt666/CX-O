import { type SVGProps } from 'react';

/** 羽毛 图标 */
export default function Feather(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M20 4C20 4 16 4 12 8C8 12 6 18 6 18L4 20L5 21L7 19C7 19 13 17 17 13C21 9 20 4 20 4ZM16 6C17 6 18 7 18 8C18 10 16 12 14 14C12 16 9 17 9 17L13 13C14 12 15 11 15 10L16 6Z" />
    </svg>
  );
}
