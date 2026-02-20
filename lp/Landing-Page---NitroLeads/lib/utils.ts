import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

declare global {
  interface Window {
    fbq?: (a: string, b: string, c?: object) => void;
  }
}

/** Dispara evento Lead do Meta Pixel (para CTAs). */
export function trackMetaLead(contentName: string) {
  if (typeof window !== "undefined" && window.fbq) {
    window.fbq("track", "Lead", { content_name: contentName });
  }
}
