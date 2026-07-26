import { type SVGProps } from 'react';

/** 花朵 图标 */
export default function Flower(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M12 2C13.5 2 14.5 3.5 14.5 5C14.5 5.5 14.3 6 14 6.5C14.5 6.3 15 6 15.5 6C17 6 18.5 7 18.5 8.5C18.5 10 17 11 15.5 11C15 11 14.5 10.8 14 10.5C14.3 11 14.5 11.5 14.5 12C14.5 13.5 13.5 15 12 15C10.5 15 9.5 13.5 9.5 12C9.5 11.5 9.7 11 10 10.5C9.5 10.8 9 11 8.5 11C7 11 5.5 10 5.5 8.5C5.5 7 7 6 8.5 6C9 6 9.5 6.3 10 6.5C9.7 6 9.5 5.5 9.5 5C9.5 3.5 10.5 2 12 2ZM12 14C13 14 14 15 14 16V20C14 21 13 22 12 22C11 22 10 21 10 20V16C10 15 11 14 12 14Z" />
    </svg>
  );
}
