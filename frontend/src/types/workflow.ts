export interface WorkflowStep {
  id: string;
  description?: string;
  intent?: string | null;
  capability?: string | null;
  requires_input?: boolean;
  question?: string | null;
  inputs?: Record<string, unknown>;
  dynamic?: boolean;
  workflow_ref?: string | null;
  template?: string | null;
}

export interface Workflow {
  id: string;
  name: string;
  description: string;
  trigger_intent_pattern: string;
  steps: WorkflowStep[];
  priority: number;
  max_nodes: number;
  enabled: boolean;
  version: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface WorkflowList {
  workflows: Workflow[];
  count: number;
}

export interface Task {
  id: string;
  task_type: string;
  payload: Record<string, unknown>;
  session_id: string | null;
  status: string;
  max_attempts: number;
  attempts: number;
  schedule_cron: string | null;
  next_run_at: string | null;
  error_message: string | null;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface TaskList {
  tasks: Task[];
  count: number;
}

export interface WorkflowInstance {
  id: string;
  definition_id: string;
  session_id: string | null;
  status: string;
  current_step: number | null;
  collected: Record<string, unknown>;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
}
