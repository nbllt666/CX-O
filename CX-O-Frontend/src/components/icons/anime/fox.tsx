import { type SVGProps } from 'react';

/** 狐狸 图标 */
export default function Fox(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M4 4L8 8C8 8 6 10 6 13C6 16 9 18 12 18C15 18 18 16 18 13C18 10 16 8 16 8L20 4C20 4 18 6 16 6C14 6 13 5 12 5C11 5 10 6 8 6C6 6 4 4 4 4ZM10 12C10.5 12 11 12.5 11 13C11 13.5 10.5 14 10 14C9.5 14 9 13.5 9 13C9 12.5 9.5 12 10 12ZM14 12C14.5 12 15 12.5 15 13C15 13.5 14.5 14 14 14C13.5 14 13 13.5 13 13C13 12.5 13.5 12 14 12Z" />
    </svg>
  );
}
