import React from 'react';

export const BubbleTail = ({ className }: { className?: string }) => (
  <svg
    width="24"
    height="24"
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ overflow: 'visible' }}
  >
    <path
      d="M0 0 C4 0 8 18 12 18 C16 18 20 0 24 0"
      fill="white" 
      stroke="#FDE68A"
      strokeWidth="1"
    />
    <path d="M1 0 H23" stroke="white" strokeWidth="2" />
  </svg>
);
