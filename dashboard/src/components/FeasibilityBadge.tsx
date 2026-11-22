import React from 'react';
import { AIFeasibility, AIProduction } from '../api/types';

export interface FeasibilityBadgeProps {
  feasibility?: AIFeasibility | AIProduction | null;
  className?: string;
  style?: React.CSSProperties;
}

export const FeasibilityBadge: React.FC<FeasibilityBadgeProps> = ({
  feasibility,
  className = '',
  style,
}) => {
  const value: AIFeasibility | null | undefined =
    typeof feasibility === 'object' && feasibility !== null
      ? feasibility.feasibility
      : feasibility;

  let label = 'Chưa đánh giá';
  let badgeClass = 'badge-p3';

  if (value === 'CAO') {
    label = 'Làm bằng AI: Cao';
    badgeClass = 'badge-success';
  } else if (value === 'TRUNG_BINH') {
    label = 'Làm bằng AI: Trung bình';
    badgeClass = 'badge-warning';
  } else if (value === 'THAP') {
    label = 'Làm bằng AI: Thấp';
    badgeClass = 'badge-danger';
  } else {
    label = 'Chưa đánh giá';
    badgeClass = 'badge-p3';
  }

  return (
    <span className={`badge ${badgeClass} ${className}`.trim()} style={style}>
      {label}
    </span>
  );
};
