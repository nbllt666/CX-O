import { type SVGProps } from 'react';

/** 音符♪ 图标 */
export default function MusicNote(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M9 3v10.55A4 4 0 1 0 11 17V7h6V3H9z" />
    </svg>
  );
}
