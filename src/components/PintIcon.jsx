import React from 'react';

export function PintIcon({ size = 24, status = 'confirmed_draught' }) {
  const borderColor =
    status === 'confirmed_draught'
      ? '#15803d'
      : status === 'cans_or_bottles'
      ? '#4ade80'
      : status === 'likely_serves'
      ? '#fbbf24'
      : status === 'no_guinness'
      ? '#f87171'
      : '#8c7e6d';

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 36 36"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      style={{ flexShrink: 0 }}
    >
      {/* Outer Glow Circle */}
      <circle cx="18" cy="18" r="17" fill="#171310" stroke={borderColor} strokeWidth="2" />
      {/* Creamy Head Foam */}
      <path
        d="M11 9.5C11 8.4 11.9 7.5 13 7.5H23C24.1 7.5 25 8.4 25 9.5V12.5H11V9.5Z"
        fill="#F5EFE6"
      />
      {/* Dark Ruby/Black Stout Body */}
      <path d="M11 12.5H25L23.2 27.5C23.1 28.3 22.4 29 21.6 29H14.4C13.6 29 12.9 28.3 12.8 27.5L11 12.5Z" fill="#0A0806" />
      {/* Pint Glass Outline */}
      <path
        d="M11 9.5C11 8.4 11.9 7.5 13 7.5H23C24.1 7.5 25 8.4 25 9.5L23.2 27.5C23.1 28.3 22.4 29 21.6 29H14.4C13.6 29 12.9 28.3 12.8 27.5L11 9.5Z"
        stroke={borderColor}
        strokeWidth="1.4"
      />
      {/* Mini Gold Harp Emblem */}
      <path
        d="M16.5 16.5V22.5C16.5 22.5 19.8 21.2 19.8 18.2C19.8 16.8 16.5 16.5 16.5 16.5Z"
        stroke="#C8A45D"
        strokeWidth="1.3"
        fill="rgba(200, 164, 93, 0.25)"
      />
    </svg>
  );
}

export function createMarkerSvgDataUrl(status = 'confirmed_draught', isSelected = false) {
  const ringColor = isSelected
    ? '#ffffff'
    : status === 'confirmed_draught'
    ? '#15803d'
    : status === 'cans_or_bottles'
    ? '#4ade80'
    : status === 'likely_serves'
    ? '#fbbf24'
    : status === 'no_guinness'
    ? '#f87171'
    : '#9ca3af';

  const scale = isSelected ? 44 : 36;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${scale}" height="${scale}" viewBox="0 0 40 40">
    <circle cx="20" cy="20" r="18" fill="#14110e" stroke="${ringColor}" stroke-width="${isSelected ? '3.2' : '2.4'}"/>
    <path d="M13 10.5C13 9.4 13.9 8.5 15 8.5H25C26.1 8.5 27 9.4 27 10.5V13.8H13V10.5Z" fill="#F5EFE6"/>
    <path d="M13 13.8H27L25.1 29.2C25 30 24.3 30.7 23.5 30.7H16.5C15.7 30.7 15 30 14.9 29.2L13 13.8Z" fill="#090705"/>
    <path d="M13 10.5C13 9.4 13.9 8.5 15 8.5H25C26.1 8.5 27 9.4 27 10.5L25.1 29.2C25 30 24.3 30.7 23.5 30.7H16.5C15.7 30.7 15 30 14.9 29.2L13 10.5Z" stroke="#C8A45D" stroke-width="1.3" fill="none"/>
    <path d="M18.2 17.5V23.8C18.2 23.8 21.8 22.4 21.8 19.3C21.8 17.8 18.2 17.5 18.2 17.5Z" stroke="#C8A45D" stroke-width="1.3" fill="#C8A45D"/>
  </svg>`;

  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

export function formatCategoryLabel(category) {
  switch (category) {
    case 'pub':
      return 'Pub';
    case 'bar':
      return 'Bar';
    case 'hotel':
      return 'Hotel';
    case 'restaurant':
      return 'Restaurant';
    default:
      return 'Venue';
  }
}
