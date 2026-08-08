import { useMemo, useState } from "react";
import { CheckCircle2, AlertCircle, Wand2 } from "lucide-react";

interface JsonFieldProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
  /** JSON templates the user can insert with one click. */
  presets?: { label: string; json: string }[];
}

/**
 * JSON textarea with live syntax validation and one-click template presets.
 * Shows a green "valid JSON" or red error hint as the user types.
 */
export default function JsonField({
  value,
  onChange,
  placeholder = '{"type": "object", "properties": {}}',
  rows = 6,
  presets = [],
}: JsonFieldProps) {
  const [showPresets, setShowPresets] = useState(false);

  const validation = useMemo(() => {
    const trimmed = value.trim();
    if (!trimmed) return { state: "empty" as const, message: "Optional — leave {} if not needed." };
    try {
      const parsed = JSON.parse(trimmed) as unknown;
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        return { state: "error" as const, message: "Must be a JSON object, not an array or scalar." };
      }
      return { state: "valid" as const, message: "Valid JSON." };
    } catch (err) {
      return {
        state: "error" as const,
        message: err instanceof Error ? err.message : "Invalid JSON.",
      };
    }
  }, [value]);

  return (
    <div className="space-y-1.5">
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={rows}
        spellCheck={false}
        className="flex w-full rounded-lg border border-input bg-transparent px-3 py-2 font-mono text-xs placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
      />
      <div className="flex items-center justify-between gap-2">
        <p
          className={`flex items-center gap-1 text-xs ${
            validation.state === "error"
              ? "text-destructive"
              : validation.state === "valid"
                ? "text-green-600 dark:text-green-400"
                : "text-muted-foreground"
          }`}
        >
          {validation.state === "error" && <AlertCircle className="h-3 w-3" />}
          {validation.state === "valid" && <CheckCircle2 className="h-3 w-3" />}
          {validation.message}
        </p>
        {presets.length > 0 && (
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setShowPresets((v) => !v)}
              className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline"
            >
              <Wand2 className="h-3 w-3" /> Insert template
            </button>
            {showPresets && (
              <div className="flex flex-wrap gap-1">
                {presets.map((p) => (
                  <button
                    key={p.label}
                    type="button"
                    onClick={() => {
                      onChange(p.json);
                      setShowPresets(false);
                    }}
                    className="rounded border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground"
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
