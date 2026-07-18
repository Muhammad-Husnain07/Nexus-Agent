export type SchemaFieldType = "string" | "number" | "integer" | "boolean" | "array" | "object" | "null"

export type StringFormat = "email" | "uri" | "date-time" | "date" | "time" | "uuid" | "hostname" | "ipv4" | "ipv6" | "regex" | "json-pointer" | "relative-json-pointer"

export interface SchemaConstraints {
  minLength?: number
  maxLength?: number
  minimum?: number
  maximum?: number
  exclusiveMinimum?: number
  exclusiveMaximum?: number
  pattern?: string
  enum?: string[]
}

export interface SchemaProperty {
  key: string
  type: SchemaFieldType
  required: boolean
  description?: string
  default?: unknown
  examples?: unknown[]
  format?: StringFormat
  constraints?: SchemaConstraints
  properties?: SchemaProperty[]
  items?: SchemaProperty
  additionalProperties?: boolean
}

export interface JsonSchemaDraft7 {
  $schema?: string
  type: "object"
  title?: string
  description?: string
  required?: string[]
  properties?: Record<string, SchemaPropertyRaw>
  additionalProperties?: boolean
}

export interface SchemaPropertyRaw {
  type?: string
  description?: string
  default?: unknown
  examples?: unknown[]
  format?: string
  minLength?: number
  maxLength?: number
  minimum?: number
  maximum?: number
  pattern?: string
  enum?: string[]
  properties?: Record<string, SchemaPropertyRaw>
  items?: SchemaPropertyRaw
  required?: string[]
  additionalProperties?: boolean
}
