import { type SVGProps } from 'react';

/** 猫爪 图标 */
export default function CatPaw(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M8 2C9 2 10 3 10 5C10 7 9 8 8 8C7 8 6 7 6 5C6 3 7 2 8 2ZM16 2C17 2 18 3 18 5C18 7 17 8 16 8C15 8 14 7 14 5C14 3 15 2 16 2ZM4 7C5 7 6 8 6 10C6 11 5 12 4 12C3 12 2 11 2 10C2 8 3 7 4 7ZM20 7C21 7 22 8 22 10C22 11 21 12 20 12C19 12 18 11 18 10C18 8 19 7 20 7ZM12 11C14 11 17 13 17 16C17 18 15 20 12 20C9 20 7 18 7 16C7 13 10 11 12 11Z" />
    </svg>
  );
}
