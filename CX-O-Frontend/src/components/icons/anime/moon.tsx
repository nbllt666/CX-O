import { type SVGProps } from 'react';

/** 月亮 图标 */
export default function Moon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M12 3C10.5 3 9 3.5 7.8 4.3C11 4.8 13.5 7.5 13.5 11C13.5 14.5 11 17.2 7.8 17.7C9 18.5 10.5 19 12 19C16 19 19 16 19 12C19 8 16 3 12 3Z" />
    </svg>
  );
}
