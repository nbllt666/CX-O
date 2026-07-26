import { type SVGProps } from 'react';

/** 水晶♦ 图标 */
export default function Crystal(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M12 2L4 9L12 22L20 9L12 2ZM12 5.5L17 9L12 17L7 9L12 5.5Z" />
    </svg>
  );
}
