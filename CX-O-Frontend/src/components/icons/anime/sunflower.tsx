import { type SVGProps } from 'react';

/** 向日葵 图标 */
export default function Sunflower(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M12 2L13 5L16 4L15 7L18 8L15 9L16 12L13 11L12 14L11 11L8 12L9 9L6 8L9 7L8 4L11 5L12 2ZM12 8C10 8 9 9 9 11C9 13 10 14 12 14C14 14 15 13 15 11C15 9 14 8 12 8ZM11 14V20H13V14H11Z" />
    </svg>
  );
}
