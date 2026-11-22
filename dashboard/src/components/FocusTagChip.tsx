import React from 'react';
import { FocusTag } from '../api/types';

export const FOCUS_TAG_LABELS: Record<FocusTag, string> = {
  phim_ngan: 'Phim ngắn',
  micro_drama: 'Micro-drama',
  giai_tri: 'Giải trí',
  ai_san_xuat: 'Sản xuất bằng AI',
};

export interface FocusTagChipProps {
  tag: FocusTag | string;
  className?: string;
  style?: React.CSSProperties;
}

export const FocusTagChip: React.FC<FocusTagChipProps> = ({ tag, className = '', style }) => {
  const label = FOCUS_TAG_LABELS[tag as FocusTag] || tag;

  return (
    <span
      className={`badge badge-purple ${className}`.trim()}
      style={{
        textTransform: 'none',
        fontWeight: 500,
        ...style,
      }}
    >
      {label}
    </span>
  );
};
