import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Box, Stepper, Step, StepLabel, Button, Typography, TextField,
  Card, CardContent, Select, MenuItem, FormControl, InputLabel, Switch,
  FormControlLabel, Chip, Autocomplete, IconButton,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import ArrowForwardIcon from "@mui/icons-material/ArrowForward";
import CheckIcon from "@mui/icons-material/Check";
import PreviewIcon from "@mui/icons-material/Preview";

const steps = [
  "Basic Info",
  "API Configuration",
  "Authentication",
  "Input Schema",
  "Output Schema",
  "Examples",
  "Risk & Approval",
];

export default function ToolBuilderForm() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [activeStep, setActiveStep] = useState(0);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const isEdit = !!id;

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>
        {isEdit ? "Edit Tool" : "Create Tool"}
      </Typography>

      <Stepper activeStep={activeStep} sx={{ mb: 4 }}>
        {steps.map((label) => (
          <Step key={label}>
            <StepLabel>{label}</StepLabel>
          </Step>
        ))}
      </Stepper>

      <Card>
        <CardContent>
          {activeStep === 0 && (
            <Box display="flex" flexDirection="column" gap={2}>
              <TextField
                fullWidth
                label="Tool Name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
              <TextField
                fullWidth
                label="Description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                multiline
                rows={3}
                required
              />
              <FormControl fullWidth>
                <InputLabel>Category</InputLabel>
                <Select label="Category">
                  <MenuItem value="data">Data</MenuItem>
                  <MenuItem value="entertainment">Entertainment</MenuItem>
                  <MenuItem value="dev">Dev Tools</MenuItem>
                  <MenuItem value="education">Education</MenuItem>
                </Select>
              </FormControl>
              <Autocomplete
                multiple
                options={[]}
                freeSolo
                renderInput={(params) => <TextField {...params} label="Tags" />}
              />
            </Box>
          )}

          {activeStep === 6 && (
            <Box display="flex" flexDirection="column" gap={2}>
              <FormControlLabel control={<Switch />} label="Requires Approval" />
              <FormControl fullWidth>
                <InputLabel>Risk Level</InputLabel>
                <Select label="Risk Level" defaultValue="low">
                  <MenuItem value="low">Low</MenuItem>
                  <MenuItem value="medium">Medium</MenuItem>
                  <MenuItem value="high">High</MenuItem>
                  <MenuItem value="critical">Critical</MenuItem>
                </Select>
              </FormControl>
            </Box>
          )}

          {activeStep !== 0 && activeStep !== 6 && (
            <Typography color="text.secondary">
              Step {activeStep + 1}: {steps[activeStep]}
            </Typography>
          )}
        </CardContent>
      </Card>

      <Box display="flex" justifyContent="space-between" mt={3}>
        <Button
          disabled={activeStep === 0}
          onClick={() => setActiveStep((p) => p - 1)}
          startIcon={<ArrowBackIcon />}
        >
          Back
        </Button>
        <Box display="flex" gap={1}>
          {activeStep === steps.length - 1 ? (
            <Button variant="contained" startIcon={<CheckIcon />}>
              {isEdit ? "Update Tool" : "Create Tool"}
            </Button>
          ) : (
            <Button
              variant="contained"
              onClick={() => setActiveStep((p) => p + 1)}
              endIcon={<ArrowForwardIcon />}
            >
              Next
            </Button>
          )}
        </Box>
      </Box>
    </Box>
  );
}
