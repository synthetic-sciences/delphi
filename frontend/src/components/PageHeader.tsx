"use client";

import { ReactNode } from "react";
import { Plus } from "lucide-react";

interface PageHeaderProps {
  title: string;
  description?: string;
  action?: {
    label: string;
    onClick?: () => void;
    href?: string;
  };
  children?: ReactNode;
}

export default function PageHeader({ title, description, action, children }: PageHeaderProps) {
  return (
    <div className="flex items-start justify-between mb-6">
      <div>
        <h1 className="text-2xl font-semibold text-[#2e2522]">{title}</h1>
        {description && <p className="text-[#8a7a72] text-sm mt-1">{description}</p>}
      </div>
      <div className="flex items-center gap-3">
        {children}
        {action && (
          <button
            onClick={action.onClick}
            className="h-9 px-4 rounded-lg bg-[#2e2522] text-[#f7f0e8] text-sm font-medium hover:bg-[#3a3230] transition-colors flex items-center gap-2"
          >
            <Plus size={16} />
            {action.label}
          </button>
        )}
      </div>
    </div>
  );
}
