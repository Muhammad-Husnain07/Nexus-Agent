import { useState, useCallback, useMemo } from "react"
import { DndContext, closestCenter, KeyboardSensor, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core"
import { SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy, useSortable } from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { GripVertical, Plus, Trash2, Copy, FileUp, FileDown, Eye, Code2 } from "lucide-react"
import type { SchemaProperty, SchemaFieldType, StringFormat } from "@/types/schema"

function generateId(): string {
  return Math.random().toString(36).substring(2, 9)
}

function newProperty(key?: string): SchemaProperty {
  return { key: key || generateId(), type: "string", required: false }
}

const FIELD_TYPES: { value: SchemaFieldType; label: string }[] = [
  { value: "string", label: "String" },
  { value: "number", label: "Number" },
  { value: "integer", label: "Integer" },
  { value: "boolean", label: "Boolean" },
  { value: "array", label: "Array" },
  { value: "object", label: "Object" },
  { value: "null", label: "Null" },
]

const STRING_FORMATS: { value: StringFormat; label: string }[] = [
  { value: "email", label: "Email" },
  { value: "uri", label: "URI" },
  { value: "date-time", label: "Date-Time" },
  { value: "date", label: "Date" },
  { value: "time", label: "Time" },
  { value: "uuid", label: "UUID" },
  { value: "hostname", label: "Hostname" },
  { value: "ipv4", label: "IPv4" },
  { value: "ipv6", label: "IPv6" },
]

function SortableProperty({
  property,
  depth,
  onEdit,
  onDelete,
  onAddChild,
}: {
  property: SchemaProperty
  depth: number
  onEdit: () => void
  onDelete: () => void
  onAddChild: () => void
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: property.key })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  const typeColors: Record<string, string> = {
    string: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-100",
    number: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-100",
    integer: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-100",
    boolean: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-100",
    array: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100",
    object: "bg-cyan-100 text-cyan-800 dark:bg-cyan-900 dark:text-cyan-100",
    null: "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-100",
  }

  return (
    <div ref={setNodeRef} style={style} className="group border rounded-md p-2 mb-1 bg-card" style={{ marginLeft: depth * 20 }}>
      <div className="flex items-center gap-2">
        <button {...attributes} {...listeners} className="cursor-grab text-muted-foreground hover:text-foreground">
          <GripVertical className="h-4 w-4" />
        </button>
        <span className="font-mono text-sm font-medium">{property.key}</span>
        <Badge className={`text-xs ${typeColors[property.type] || ""}`}>{property.type}</Badge>
        {property.required && <Badge variant="destructive" className="text-xs">required</Badge>}
        <div className="ml-auto flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onEdit} title="Edit">
            <Code2 className="h-3 w-3" />
          </Button>
          {(property.type === "object" || property.type === "array") && (
            <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onAddChild} title="Add child">
              <Plus className="h-3 w-3" />
            </Button>
          )}
          <Button variant="ghost" size="icon" className="h-6 w-6 text-destructive" onClick={onDelete} title="Delete">
            <Trash2 className="h-3 w-3" />
          </Button>
        </div>
      </div>
      {property.type === "object" && property.properties && property.properties.length > 0 && (
        <div className="mt-1 pl-2 border-l-2 border-muted">
          {property.properties.map((child) => (
            <SortableProperty
              key={child.key}
              property={child}
              depth={depth + 1}
              onEdit={() => {}}
              onDelete={() => {}}
              onAddChild={() => {}}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function PropertyEditor({
  property,
  onChange,
  onClose,
}: {
  property: SchemaProperty
  onChange: (p: SchemaProperty) => void
  onClose: () => void
}) {
  const [local, setLocal] = useState<SchemaProperty>({ ...property })

  const update = useCallback(<K extends keyof SchemaProperty>(field: K, value: SchemaProperty[K]) => {
    setLocal((prev) => ({ ...prev, [field]: value }))
  }, [])

  const handleSave = () => {
    onChange(local)
    onClose()
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <Label>Field Name</Label>
          <Input value={local.key} onChange={(e) => update("key", e.target.value)} />
        </div>
        <div>
          <Label>Type</Label>
          <Select
            value={local.type}
            onChange={(e) => update("type", e.target.value as SchemaFieldType)}
            options={FIELD_TYPES}
          />
        </div>
      </div>

      {local.type === "string" && (
        <div>
          <Label>Format</Label>
          <Select
            value={local.format || ""}
            onChange={(e) => update("format", e.target.value ? (e.target.value as StringFormat) : undefined)}
            options={[{ value: "", label: "None" }, ...STRING_FORMATS]}
          />
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        {(local.type === "string") && (
          <>
            <div>
              <Label>Min Length</Label>
              <Input type="number" value={local.constraints?.minLength ?? ""}
                onChange={(e) => update("constraints", { ...local.constraints, minLength: e.target.value ? Number(e.target.value) : undefined })}
              />
            </div>
            <div>
              <Label>Max Length</Label>
              <Input type="number" value={local.constraints?.maxLength ?? ""}
                onChange={(e) => update("constraints", { ...local.constraints, maxLength: e.target.value ? Number(e.target.value) : undefined })}
              />
            </div>
          </>
        )}
        {(local.type === "number" || local.type === "integer") && (
          <>
            <div>
              <Label>Minimum</Label>
              <Input type="number" value={local.constraints?.minimum ?? ""}
                onChange={(e) => update("constraints", { ...local.constraints, minimum: e.target.value ? Number(e.target.value) : undefined })}
              />
            </div>
            <div>
              <Label>Maximum</Label>
              <Input type="number" value={local.constraints?.maximum ?? ""}
                onChange={(e) => update("constraints", { ...local.constraints, maximum: e.target.value ? Number(e.target.value) : undefined })}
              />
            </div>
          </>
        )}
      </div>

      <div>
        <Label>Pattern (regex)</Label>
        <Input value={local.constraints?.pattern || ""}
          onChange={(e) => update("constraints", { ...local.constraints, pattern: e.target.value || undefined })}
        />
      </div>

      <div>
        <Label>Enum Values (comma-separated)</Label>
        <Input value={local.constraints?.enum?.join(", ") || ""}
          onChange={(e) => update("constraints", { ...local.constraints, enum: e.target.value ? e.target.value.split(",").map(s => s.trim()) : undefined })}
        />
      </div>

      <div className="flex items-center gap-2">
        <input type="checkbox" id="required" checked={local.required}
          onChange={(e) => update("required", e.target.checked)}
          className="rounded border-gray-300"
        />
        <Label htmlFor="required">Required</Label>
      </div>

      <div>
        <Label>Description</Label>
        <Textarea value={local.description || ""} onChange={(e) => update("description", e.target.value || undefined)} />
      </div>

      <div>
        <Label>Default Value</Label>
        <Input value={local.default !== undefined ? String(local.default) : ""}
          onChange={(e) => update("default", e.target.value || undefined)}
        />
      </div>

      <div className="flex justify-end gap-2 pt-2">
        <Button variant="outline" onClick={onClose}>Cancel</Button>
        <Button onClick={handleSave}>Save</Button>
      </div>
    </div>
  )
}

function schemaToJsonSchema(properties: SchemaProperty[], title?: string): Record<string, unknown> {
  const schema: Record<string, unknown> = {
    $schema: "http://json-schema.org/draft-07/schema#",
    type: "object",
    title: title || "Generated Schema",
  }

  const requiredFields = properties.filter((p) => p.required).map((p) => p.key)
  if (requiredFields.length > 0) schema.required = requiredFields

  const propsRecord: Record<string, unknown> = {}
  for (const prop of properties) {
    propsRecord[prop.key] = propertyToJsonSchema(prop)
  }
  if (Object.keys(propsRecord).length > 0) schema.properties = propsRecord

  return schema
}

function propertyToJsonSchema(prop: SchemaProperty): Record<string, unknown> {
  const result: Record<string, unknown> = { type: prop.type }
  if (prop.description) result.description = prop.description
  if (prop.default !== undefined) result.default = prop.default
  if (prop.examples && prop.examples.length > 0) result.examples = prop.examples
  if (prop.format) result.format = prop.format
  if (prop.constraints?.minLength !== undefined) result.minLength = prop.constraints.minLength
  if (prop.constraints?.maxLength !== undefined) result.maxLength = prop.constraints.maxLength
  if (prop.constraints?.minimum !== undefined) result.minimum = prop.constraints.minimum
  if (prop.constraints?.maximum !== undefined) result.maximum = prop.constraints.maximum
  if (prop.constraints?.pattern) result.pattern = prop.constraints.pattern
  if (prop.constraints?.enum) result.enum = prop.constraints.enum

  if (prop.type === "object" && prop.properties && prop.properties.length > 0) {
    const childRequired = prop.properties.filter((p) => p.required).map((p) => p.key)
    if (childRequired.length > 0) result.required = childRequired
    const childProps: Record<string, unknown> = {}
    for (const child of prop.properties) {
      childProps[child.key] = propertyToJsonSchema(child)
    }
    result.properties = childProps
    if (prop.additionalProperties !== undefined) result.additionalProperties = prop.additionalProperties
  }

  if (prop.type === "array" && prop.items) {
    result.items = propertyToJsonSchema(prop.items)
  }

  return result
}

function jsonSchemaToProperties(schema: Record<string, unknown>): SchemaProperty[] {
  const props = (schema.properties as Record<string, unknown> | undefined) || {}
  const required = new Set<string>((schema.required as string[]) || [])
  return Object.entries(props).map(([key, val]) => {
    const v = val as Record<string, unknown>
    const prop: SchemaProperty = {
      key,
      type: (v.type as SchemaFieldType) || "string",
      required: required.has(key),
      description: v.description as string | undefined,
      default: v.default,
      format: v.format as StringFormat | undefined,
      constraints: {
        minLength: v.minLength as number | undefined,
        maxLength: v.maxLength as number | undefined,
        minimum: v.minimum as number | undefined,
        maximum: v.maximum as number | undefined,
        pattern: v.pattern as string | undefined,
        enum: v.enum as string[] | undefined,
      },
    }

    if (prop.type === "object" && v.properties) {
      prop.properties = jsonSchemaToProperties(v as Record<string, unknown>)
    }
    if (prop.type === "array" && v.items) {
      const items = v.items as Record<string, unknown>
      prop.items = {
        key: "items",
        type: (items.type as SchemaFieldType) || "string",
        required: false,
        description: items.description as string | undefined,
        constraints: {},
      }
      if (items.properties) {
        prop.items.type = "object"
        prop.items.properties = jsonSchemaToProperties(items)
      }
    }

    return prop
  })
}

interface JsonSchemaEditorProps {
  value?: Record<string, unknown>
  onChange?: (schema: Record<string, unknown>) => void
  title?: string
}

export default function JsonSchemaEditor({ value, onChange, title }: JsonSchemaEditorProps) {
  const [properties, setProperties] = useState<SchemaProperty[]>(() => value ? jsonSchemaToProperties(value) : [])
  const [editingProp, setEditingProp] = useState<SchemaProperty | null>(null)
  const [showPreview, setShowPreview] = useState(false)
  const [showCodeEditor, setShowCodeEditor] = useState(false)
  const [codeText, setCodeText] = useState("")

  const generatedSchema = useMemo(() => schemaToJsonSchema(properties, title), [properties, title])

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const handleDragEnd = useCallback((event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    setProperties((prev) => {
      const oldIndex = prev.findIndex((p) => p.key === active.id)
      const newIndex = prev.findIndex((p) => p.key === over.id)
      if (oldIndex === -1 || newIndex === -1) return prev
      const next = [...prev]
      const [moved] = next.splice(oldIndex, 1)
      next.splice(newIndex, 0, moved)
      return next
    })
  }, [])

  const addProperty = useCallback(() => {
    const prop = newProperty()
    setProperties((prev) => [...prev, prop])
    setEditingProp(prop)
  }, [])

  const deleteProperty = useCallback((key: string) => {
    setProperties((prev) => prev.filter((p) => p.key !== key))
  }, [])

  const updateProperty = useCallback((updated: SchemaProperty) => {
    setProperties((prev) => prev.map((p) => (p.key === updated.key ? updated : p)))
    if (onChange) onChange(generatedSchema)
  }, [generatedSchema, onChange])

  const importSchema = useCallback(() => {
    const input = document.createElement("input")
    input.type = "file"
    input.accept = ".json"
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0]
      if (!file) return
      const text = await file.text()
      try {
        const schema = JSON.parse(text)
        setProperties(jsonSchemaToProperties(schema))
      } catch {
        alert("Invalid JSON Schema file")
      }
    }
    input.click()
  }, [])

  const exportSchema = useCallback(() => {
    const blob = new Blob([JSON.stringify(generatedSchema, null, 2)], { type: "application/json" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${title || "schema"}.json`
    a.click()
    URL.revokeObjectURL(url)
  }, [generatedSchema, title])

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={addProperty}>
            <Plus className="h-4 w-4 mr-1" /> Add Property
          </Button>
          <Button variant="outline" size="sm" onClick={importSchema}>
            <FileUp className="h-4 w-4 mr-1" /> Import
          </Button>
          <Button variant="outline" size="sm" onClick={exportSchema}>
            <FileDown className="h-4 w-4 mr-1" /> Export
          </Button>
        </div>
        <div className="flex gap-2">
          <Button variant={showPreview ? "default" : "outline"} size="sm" onClick={() => setShowPreview(!showPreview)}>
            <Eye className="h-4 w-4 mr-1" /> Preview
          </Button>
          <Button variant={showCodeEditor ? "default" : "outline"} size="sm" onClick={() => {
            setShowCodeEditor(!showCodeEditor)
            if (!showCodeEditor) setCodeText(JSON.stringify(generatedSchema, null, 2))
          }}>
            <Code2 className="h-4 w-4 mr-1" /> Code
          </Button>
        </div>
      </div>

      {showCodeEditor ? (
        <div className="border rounded-md">
          <textarea
            className="w-full h-64 p-4 font-mono text-sm bg-muted resize-y focus:outline-none"
            value={codeText}
            onChange={(e) => setCodeText(e.target.value)}
          />
          <div className="flex justify-end gap-2 p-2 border-t">
            <Button variant="outline" size="sm" onClick={() => {
              setShowCodeEditor(false)
            }}>Cancel</Button>
            <Button size="sm" onClick={() => {
              try {
                const parsed = JSON.parse(codeText)
                setProperties(jsonSchemaToProperties(parsed))
                setShowCodeEditor(false)
              } catch {
                alert("Invalid JSON")
              }
            }}>Apply</Button>
          </div>
        </div>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={properties.map(p => p.key)} strategy={verticalListSortingStrategy}>
            <div className="space-y-1">
              {properties.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-8">
                  No properties defined. Click "Add Property" to start.
                </p>
              ) : (
                properties.map((prop) => (
                  <SortableProperty
                    key={prop.key}
                    property={prop}
                    depth={0}
                    onEdit={() => setEditingProp({ ...prop })}
                    onDelete={() => deleteProperty(prop.key)}
                    onAddChild={() => {
                      const child = newProperty()
                      setProperties((prev) =>
                        prev.map((p) =>
                          p.key === prop.key
                            ? { ...p, properties: [...(p.properties || []), child] }
                            : p
                        )
                      )
                    }}
                  />
                ))
              )}
            </div>
          </SortableContext>
        </DndContext>
      )}

      {showPreview && (
        <Card>
          <CardHeader><CardTitle className="text-sm">Generated JSON Schema</CardTitle></CardHeader>
          <CardContent>
            <ScrollArea className="h-64">
              <pre className="text-xs font-mono">{JSON.stringify(generatedSchema, null, 2)}</pre>
            </ScrollArea>
          </CardContent>
        </Card>
      )}

      <Dialog open={!!editingProp} onOpenChange={(open) => { if (!open) setEditingProp(null) }}>
        {editingProp && (
          <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>Edit Property: {editingProp.key}</DialogTitle>
              <DialogDescription>Configure the schema property settings</DialogDescription>
            </DialogHeader>
            <PropertyEditor
              property={editingProp}
              onChange={updateProperty}
              onClose={() => setEditingProp(null)}
            />
          </DialogContent>
        )}
      </Dialog>
    </div>
  )
}
