import React from 'react';

/**
 * DaOneLogo: Premium vector SVG component with continuous animated drawing loop.
 * Renders the interwoven D-A ribbon emblem and bold DA-ONE typography.
 */
export default function DaOneLogo({ height = 36, showText = true, animated = true, className = '' }) {
  return (
    <div className={`da-logo-container ${animated ? 'animated-loop' : ''} ${className}`} style={{ display: 'inline-flex', alignItems: 'center', height }}>
      <svg 
        viewBox={showText ? "0 0 380 96" : "0 0 124 96"} 
        height={height} 
        style={{ width: 'auto', maxHeight: '100%', overflow: 'visible' }}
        fill="none" 
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          {/* Teal Gradient for D loop */}
          <linearGradient id="tealLoop" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#14b8a6" />
            <stop offset="50%" stopColor="#115e59" />
            <stop offset="100%" stopColor="#0b3b3c" />
          </linearGradient>

          {/* Copper Gradient for A loop */}
          <linearGradient id="copperLoop" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#e08343" />
            <stop offset="50%" stopColor="#c27847" />
            <stop offset="100%" stopColor="#8a4823" />
          </linearGradient>

          {/* Glow filter */}
          <filter id="logoGlow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="2.5" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        {/* EMBLEM GROUP: Interwoven D & A ribbons */}
        <g className="da-emblem-group" transform="translate(4, 4)">
          {/* Outer D Ribbon (Forest Teal) */}
          <path
            className="da-svg-path path-teal"
            d="M 12 12 L 38 12 C 65 12, 78 30, 78 44 C 78 58, 65 76, 38 76 L 12 76 Z"
            stroke="url(#tealLoop)"
            strokeWidth="11"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />

          {/* D Inner Window Highlight */}
          <path
            className="da-svg-path path-teal-inner"
            d="M 28 28 L 36 28 C 48 28, 54 35, 54 44 C 54 53, 48 60, 36 60 L 28 60 Z"
            stroke="#14b8a6"
            strokeWidth="4"
            strokeLinecap="round"
            strokeLinejoin="round"
            opacity="0.4"
            fill="none"
          />

          {/* Interwoven A Ribbon (Warm Metallic Copper) */}
          <path
            className="da-svg-path path-copper"
            d="M 52 76 L 68 20 C 72 8, 86 8, 92 20 L 108 76"
            stroke="url(#copperLoop)"
            strokeWidth="11"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />

          {/* A Crossbar */}
          <path
            className="da-svg-path path-copper-cross"
            d="M 58 52 L 102 52"
            stroke="url(#copperLoop)"
            strokeWidth="8"
            strokeLinecap="round"
            fill="none"
          />

          {/* Luminous Core Points */}
          <circle className="da-svg-dot dot-teal" cx="12" cy="12" r="3" fill="#2dd4bf" />
          <circle className="da-svg-dot dot-copper" cx="108" cy="76" r="3" fill="#e08343" />
        </g>

        {/* TYPOGRAPHY: DA-ONE */}
        {showText && (
          <g className="da-text-group" transform="translate(136, 0)">
            {/* D Letter */}
            <path
              className="da-svg-letter letter-teal"
              d="M 6 22 L 26 22 C 40 22, 48 30, 48 44 C 48 58, 40 66, 26 66 L 6 66 Z M 16 32 L 25 32 C 34 32, 38 37, 38 44 C 38 51, 34 56, 25 56 L 16 56 Z"
              fill="#115e59"
            />

            {/* A Letter */}
            <path
              className="da-svg-letter letter-teal"
              d="M 54 66 L 68 22 L 78 22 L 92 66 L 82 66 L 79 56 L 67 56 L 64 66 Z M 69 48 L 77 48 L 73 34 Z"
              fill="#115e59"
            />

            {/* Hyphen (Copper) */}
            <rect
              className="da-svg-letter letter-copper"
              x="100"
              y="41"
              width="14"
              height="6"
              rx="3"
              fill="#c27847"
            />

            {/* O Letter (Warm Copper) */}
            <path
              className="da-svg-letter letter-copper"
              d="M 140 21 C 153 21, 162 31, 162 44 C 162 57, 153 67, 140 67 C 127 67, 118 57, 118 44 C 118 31, 127 21, 140 21 Z M 140 31 C 132 31, 128 37, 128 44 C 128 51, 132 57, 140 57 C 148 57, 152 51, 152 44 C 152 37, 148 31, 140 31 Z"
              fill="#c27847"
            />

            {/* N Letter (Warm Copper) */}
            <path
              className="da-svg-letter letter-copper"
              d="M 172 22 L 182 22 L 198 52 L 198 22 L 208 22 L 208 66 L 198 66 L 182 36 L 182 66 L 172 66 Z"
              fill="#c27847"
            />

            {/* E Letter (Warm Copper) */}
            <path
              className="da-svg-letter letter-copper"
              d="M 218 22 L 244 22 L 244 31 L 228 31 L 228 39 L 241 39 L 241 48 L 228 48 L 228 57 L 245 57 L 245 66 L 218 66 Z"
              fill="#c27847"
            />
          </g>
        )}
      </svg>
    </div>
  );
}
