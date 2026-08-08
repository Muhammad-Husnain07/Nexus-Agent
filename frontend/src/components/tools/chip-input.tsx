import { useState } from "react";
import { X, Plus } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";

interface ChipInputProps {
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  /** Deduplicate case-insensitively (default true). */
  dedupe?: boolean;
}

/**
 * Chip-style list input — type an item and press Enter (or comma) to add it
 * as a chip; click a chip's × to remove it. No comma-separated typing.
 */
export default function ChipInput({
  value = [],
  onChange,
  placeholder = "Type and press Enter…",
  disabled,
  dedupe = true,
}: ChipInputProps) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const add = (raw: string) => {
    const item = raw.trim();
    if (!item) return;
    const exists = value.some(
      (v) => v.toLowerCase() === item.toLowerCase(),
    );
    if (dedupe && exists) {
      setError(`"${item}" is already added`);
      return;
    }
    onChange([...value, item]);
    setText("");
    setError(null);
  };

  /**
   * Split comma-separated input into individual chips — so pasting or typing
   * "pokemon, api, game" adds three separate chips.
   */
  const addCommaSeparated = (raw: string) => {
    const items = raw
      .split(",")
      .map((i) => i.trim())
      .filter(Boolean);
    if (items.length === 0) {
      setText("");
      return;
    }
    const deduped: string[] = [];
    const seen = new Set(value.map((v) => v.toLowerCase()));
    for (const item of items) {
      const lower = item.toLowerCase();
      if (dedupe && seen.has(lower)) {
        setError(`"${item}" is already added`);
        continue;
      }
      if (dedupe) seen.add(lower);
      deduped.push(item);
    }
    if (deduped.length > 0) {
      onChange([...value, ...deduped]);
    }
    setText("");
    setError(null);
  };

  const remove = (idx: number) => {
    onChange(value.filter((_, i) => i !== idx));
    setError(null);
  };

  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap gap-1.5">
        {value.map((item, i) => (
          <Badge
            key={`${item}-${i}`}
            variant="secondary"
            className="gap-1 pl-2 pr-1 py-1 text-xs font-normal"
          >
            {item}
            <button
              type="button"
              onClick={() => remove(i)}
              disabled={disabled}
              className="rounded-full p-0.5 text-muted-foreground hover:bg-foreground/10 hover:text-foreground disabled:opacity-40"
              aria-label={`Remove ${item}`}
            >
              <X className="h-3 w-3" />
            </button>
          </Badge>
        ))}
      </div>
      <div className="relative">
        <Input
          value={text}
          disabled={disabled}
          placeholder={value.length === 0 ? placeholder : "Add another…"}
          onChange={(e) => {
            const raw = e.target.value;
            // Split on commas immediately — commas are separators, not text.
            if (raw.includes(",")) {
              addCommaSeparated(raw);
            } else {
              setText(raw);
              setError(null);
            }
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              addCommaSeparated(text);
            } else if (e.key === "Backspace" && !text && value.length > 0) {
              remove(value.length - 1);
            }
          }}
          onBlur={() => text.trim() && add(text)}
          className="h-8 text-xs"
        />
        {text.trim() && (
          <button
            type="button"
            onClick={() => add(text)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            aria-label="Add item"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
