import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { ArrowLeft, ArrowRight, Check } from "lucide-react"

const steps = ["Basic Info", "API Config", "Input Schema", "Risk & Approval"]

export default function ToolNewPage() {
  const [step, setStep] = useState(0)
  const [name, setName] = useState("")

  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-2xl font-bold tracking-tight">{step === 0 ? "Create Tool" : steps[step]}</h1>

      <div className="flex gap-2">
        {steps.map((s, i) => (
          <div key={s} className={`flex-1 h-1.5 rounded-full ${i <= step ? "bg-primary" : "bg-muted"}`} />
        ))}
      </div>

      <Card>
        <CardHeader><CardTitle>{steps[step]}</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          {step === 0 && (
            <>
              <div><label className="text-sm font-medium">Tool Name</label><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="my_tool" /></div>
              <div><label className="text-sm font-medium">Description</label><textarea className="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm" placeholder="Describe what this tool does" /></div>
            </>
          )}
          {step === 3 && (
            <div className="space-y-4">
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="rounded" /> Requires Approval</label>
              <div><label className="text-sm font-medium">Risk Level</label>
                <select className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm mt-1">
                  <option>low</option><option>medium</option><option>high</option><option>critical</option>
                </select></div>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="flex justify-between">
        <Button variant="outline" disabled={step === 0} onClick={() => setStep(step - 1)}><ArrowLeft size={16} /> Back</Button>
        {step < steps.length - 1 ? (
          <Button onClick={() => setStep(step + 1)}>Next <ArrowRight size={16} /></Button>
        ) : (
          <Button><Check size={16} /> Create Tool</Button>
        )}
      </div>
    </div>
  )
}
