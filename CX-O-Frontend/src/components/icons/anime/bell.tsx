import { type SVGProps } from 'react';

/** 铃铛 图标 */
export default function Bell(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M12 2C10.5 2 9.5 3 9.5 4.5V5C6.5 6 5 8.5 5 12V16L3 18V19H21V18L19 16V12C19 8.5 17.5 6 14.5 5V4.5C14.5 3 13.5 2 12 2ZM10 20C10 21.1 10.9 22 12 22C13.1 22 14 21.1 14 20H10Z" />
    </svg>
  );
}
