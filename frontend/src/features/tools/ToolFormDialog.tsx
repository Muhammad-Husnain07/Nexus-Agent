import { useMemo } from "react"
import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import { useForm, Controller } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import Dialog from "@mui/material/Dialog"
import DialogTitle from "@mui/material/DialogTitle"
import DialogContent from "@mui/material/DialogContent"
import DialogActions from "@mui/material/DialogActions"
import TextField from "@mui/material/TextField"
import Button from "@mui/material/Button"
import Select from "@mui/material/Select"
import MenuItem from "@mui/material/MenuItem"
import FormControl from "@mui/material/FormControl"
import InputLabel from "@mui/material/InputLabel"
import FormControlLabel from "@mui/material/FormControlLabel"
import Checkbox from "@mui/material/Checkbox"
import CircularProgress from "@mui/material/CircularProgress"
import Editor from "@monaco-editor/react"
import { toast } from "sonner"
import type { ToolRead } from "@/lib/types"

const httpMethods = ["GET", "POST", "PUT", "DELETE", "PATCH"] as const
const riskLevels = ["low", "medium", "high"] as const
const authTypes = ["none", "bearer", "basic", "api_key"] as const

const toolFormSchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
  description: z.string().default(""),
  purpose: z.string().default(""),
  endpoint_url: z.string().default(""),
  http_method: z.enum(httpMethods).default("GET"),
  auth_type: z.enum(authTypes).default("none"),
  risk_level: z.enum(riskLevels).default("low"),
  requires_approval: z.boolean().default(false),
  input_schema: z.string().default("{}"),
  output_schema: z.string().default("{}"),
})

export type ToolFormValues = z.infer<typeof toolFormSchema>

interface ToolFormDialogProps {
  open: boolean
  onClose: () => void
  onSubmit: (data: ToolFormValues) => Promise<void>
  tool?: ToolRead | null
  isSubmitting?: boolean
}

function formatJson(obj: Record<string, unknown>): string {
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return "{}"
  }
}

export default function ToolFormDialog({ open, onClose, onSubmit, tool, isSubmitting }: ToolFormDialogProps) {
  const isEdit = !!tool

  const defaultValues = useMemo<ToolFormValues>(() => {
    if (tool) {
      return {
        name: tool.name,
        description: tool.description ?? "",
        purpose: tool.purpose ?? "",
        endpoint_url: tool.endpoint_url ?? "",
        http_method: (tool.http_method as typeof httpMethods[number]) ?? "GET",
        auth_type: (tool.auth_type as typeof authTypes[number]) ?? "none",
        risk_level: (tool.risk_level as typeof riskLevels[number]) ?? "low",
        requires_approval: tool.requires_approval ?? false,
        input_schema: formatJson(tool.input_schema as Record<string, unknown>),
        output_schema: formatJson(tool.output_schema as Record<string, unknown>),
      }
    }
    return {
      name: "",
      description: "",
      purpose: "",
      endpoint_url: "",
      http_method: "GET",
      auth_type: "none",
      risk_level: "low",
      requires_approval: false,
      input_schema: "{}",
      output_schema: "{}",
    }
  }, [tool])

  const {
    register,
    handleSubmit,
    control,
    formState: { errors },
  } = useForm({
    resolver: zodResolver(toolFormSchema),
    values: defaultValues,
  })

  const handleFormSubmit = async (data: ToolFormValues) => {
    try {
      JSON.parse(data.input_schema)
    } catch {
      toast.error("input_schema contains invalid JSON")
      return
    }
    try {
      JSON.parse(data.output_schema)
    } catch {
      toast.error("output_schema contains invalid JSON")
      return
    }
    await onSubmit(data)
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <form onSubmit={handleSubmit(handleFormSubmit)}>
        <DialogTitle>{isEdit ? "Edit Tool" : "Register Tool"}</DialogTitle>
        <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, pt: "8px !important" }}>
          <TextField
            label="Name"
            {...register("name")}
            error={!!errors.name}
            helperText={errors.name?.message}
            size="small"
          />

          <TextField label="Description" {...register("description")} size="small" multiline rows={2} />

          <TextField label="Purpose" {...register("purpose")} size="small" multiline rows={2} />

          <TextField label="Endpoint URL" {...register("endpoint_url")} size="small" placeholder="https://api.example.com/action" />

          <Box sx={{ display: "flex", gap: 2 }}>
            <FormControl size="small" sx={{ minWidth: 140 }}>
              <InputLabel>HTTP Method</InputLabel>
              <Controller
                name="http_method"
                control={control}
                render={({ field }) => (
                  <Select label="HTTP Method" {...field}>
                    {httpMethods.map((m) => (
                      <MenuItem key={m} value={m}>{m}</MenuItem>
                    ))}
                  </Select>
                )}
              />
            </FormControl>

            <FormControl size="small" sx={{ minWidth: 140 }}>
              <InputLabel>Auth Type</InputLabel>
              <Controller
                name="auth_type"
                control={control}
                render={({ field }) => (
                  <Select label="Auth Type" {...field}>
                    {authTypes.map((a) => (
                      <MenuItem key={a} value={a}>{a}</MenuItem>
                    ))}
                  </Select>
                )}
              />
            </FormControl>

            <FormControl size="small" sx={{ minWidth: 140 }}>
              <InputLabel>Risk Level</InputLabel>
              <Controller
                name="risk_level"
                control={control}
                render={({ field }) => (
                  <Select label="Risk Level" {...field}>
                    {riskLevels.map((r) => (
                      <MenuItem key={r} value={r}>{r}</MenuItem>
                    ))}
                  </Select>
                )}
              />
            </FormControl>
          </Box>

          <FormControlLabel
            control={
              <Controller
                name="requires_approval"
                control={control}
                render={({ field }) => <Checkbox checked={field.value ?? false} onChange={field.onChange} />}
              />
            }
            label="Requires approval"
          />

          <Box>
            <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>Input Schema (JSON)</Typography>
            <Controller
              name="input_schema"
              control={control}
              render={({ field }) => (
                <Editor
                  height={150}
                  defaultLanguage="json"
                  value={field.value}
                  onChange={(v) => field.onChange(v ?? "{}")}
                  options={{ minimap: { enabled: false }, formatOnPaste: true, fontSize: 13 }}
                />
              )}
            />
          </Box>

          <Box>
            <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>Output Schema (JSON)</Typography>
            <Controller
              name="output_schema"
              control={control}
              render={({ field }) => (
                <Editor
                  height={150}
                  defaultLanguage="json"
                  value={field.value}
                  onChange={(v) => field.onChange(v ?? "{}")}
                  options={{ minimap: { enabled: false }, formatOnPaste: true, fontSize: 13 }}
                />
              )}
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose} disabled={isSubmitting}>Cancel</Button>
          <Button type="submit" variant="contained" disabled={isSubmitting}>
            {isSubmitting ? <CircularProgress size={20} /> : isEdit ? "Save" : "Register"}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  )
}
