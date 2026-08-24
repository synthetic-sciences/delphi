"use client";

import { useId, useState } from "react";

type Item = { q: string; a: string };

function FaqItem({
  item,
  open,
  onToggle,
}: {
  item: Item;
  open: boolean;
  onToggle: () => void;
}) {
  const panelId = useId();
  return (
    <div className="border-t border-border/60">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={panelId}
        className="group flex w-full items-center justify-between gap-6 py-6 text-left cursor-pointer"
      >
        <span className="text-[17px] sm:text-[19px] leading-snug text-foreground/90 group-hover:text-foreground transition-colors duration-300">
          {item.q}
        </span>
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          aria-hidden
          className={`shrink-0 text-foreground/45 transition-transform duration-300 ${
            open ? "rotate-45" : ""
          }`}
        >
          <path d="M6 1v10M1 6h10" stroke="currentColor" strokeWidth="1.2" />
        </svg>
      </button>
      <div
        id={panelId}
        className={`grid transition-[grid-template-rows] duration-500 ease-[cubic-bezier(0.19,1,0.22,1)] motion-reduce:transition-none ${
          open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
        }`}
      >
        <div className="overflow-hidden">
          <p className="pb-7 max-w-[58ch] text-[14.5px] leading-[1.7] text-foreground/65">
            {item.a}
          </p>
        </div>
      </div>
    </div>
  );
}

export function FaqList({ items }: { items: Item[] }) {
  const [openIdx, setOpenIdx] = useState(0);
  return (
    <div className="border-b border-border/60">
      {items.map((item, i) => (
        <FaqItem
          key={item.q}
          item={item}
          open={openIdx === i}
          onToggle={() => setOpenIdx(openIdx === i ? -1 : i)}
        />
      ))}
    </div>
  );
}
