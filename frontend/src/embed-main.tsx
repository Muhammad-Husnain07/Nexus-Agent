import { createRoot, type Root } from "react-dom/client";
import { StrictMode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import ChatWidget, { type WidgetConfig } from "./components/embed/chat-widget";
import "./index.css";

/**
 * Embeddable Nexus Chat Widget — UMD entry point.
 *
 * Developers embed the runtime assistant into their own applications via:
 *
 *   <script src=".../embed-widget.js"></script>
 *   <div data-nexus-chat
 *        data-api-base="https://api.example.com/api/v1"
 *        data-title="Support Assistant"
 *        data-placeholder="How can I help?"
 *        data-greeting="Hi! Ask me about anything."
 *        data-primary="#0f766e"
 *        data-height="520"
 *        data-width="380"
 *        data-launcher="true"></div>
 *
 * Or programmatically:
 *
 *   const instance = window.NexusEmbed.mount(document.body, {
 *     apiBase: "https://api.example.com/api/v1",
 *     title: "Support Assistant",
 *     launcher: true,
 *     position: "bottom-right",
 *     onEvent: (type, payload) => console.log(type, payload),
 *   });
 *
 * Config keys are read from `data-*` attributes (kebab-case) or from the
 * options object (camelCase) — options win. No values are hardcoded;
 * defaults are provided for every key so the widget works with zero config
 * against the console's own API.
 */

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false },
  },
});

const STRING_KEYS = [
  "apiBase",
  "title",
  "placeholder",
  "greeting",
  "primary",
  "sessionId",
  "storageKey",
  "position",
] as const;

const NUMERIC_KEYS = ["height", "width", "zIndex"] as const;

function readOptions(
  container: Element,
  options: Record<string, unknown> = {},
): WidgetConfig {
  const attr = (key: string) => container.getAttribute(`data-${key.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}`);
  const cfg: Record<string, unknown> = {};
  for (const key of STRING_KEYS) {
    const v = (options[key] as string | undefined) ?? attr(key);
    if (v !== null && v !== undefined) cfg[key] = v;
  }
  for (const key of NUMERIC_KEYS) {
    const raw = (options[key] as string | number | undefined) ?? attr(key);
    const num = raw === undefined || raw === null ? undefined : Number(raw);
    if (num !== undefined && !Number.isNaN(num)) cfg[key] = num;
  }
  for (const key of ["launcher", "persistSession", "streaming"] as const) {
    const raw = options[key] ?? attr(key);
    if (raw !== undefined && raw !== null) {
      cfg[key] = raw === "true" || raw === true;
    }
  }
  if (typeof options.onEvent === "function") cfg.onEvent = options.onEvent as WidgetConfig["onEvent"];
  return cfg as WidgetConfig;
}

export interface EmbedInstance {
  container: Element;
  destroy: () => void;
}

function mount(container: Element | HTMLElement, options: Record<string, unknown> = {}): EmbedInstance {
  const cfg = readOptions(container, options);
  const root: Root = createRoot(container as HTMLElement);
  root.render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <ChatWidget {...cfg} />
        <Toaster position="top-right" />
      </QueryClientProvider>
    </StrictMode>,
  );
  return {
    container,
    destroy: () => root.unmount(),
  };
}

function autoMountAll() {
  document.querySelectorAll("[data-nexus-chat]:not([data-nexus-mounted])").forEach((el) => {
    el.setAttribute("data-nexus-mounted", "true");
    mount(el);
  });
}

if (typeof window !== "undefined") {
  (window as unknown as Record<string, unknown>).NexusEmbed = { mount };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", autoMountAll);
  } else {
    autoMountAll();
  }
}

export { mount };
export type { WidgetConfig };
