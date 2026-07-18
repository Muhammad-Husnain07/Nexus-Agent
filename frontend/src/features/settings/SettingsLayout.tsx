import { useState } from "react"
import Tabs from "@mui/material/Tabs"
import Tab from "@mui/material/Tab"
import Box from "@mui/material/Box"
import ProfileTab from "./ProfileTab"
import TenantTab from "./TenantTab"
import ProvidersTab from "./ProvidersTab"
import DangerZoneTab from "./DangerZoneTab"

export default function SettingsLayout() {
  const [tab, setTab] = useState(0)

  return (
    <Box sx={{ width: "100%" }}>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ borderBottom: 1, borderColor: "divider", mb: 3 }}>
        <Tab label="Profile" />
        <Tab label="Tenant" />
        <Tab label="LLM Providers" />
        <Tab label="Danger Zone" />
      </Tabs>
      {tab === 0 && <ProfileTab />}
      {tab === 1 && <TenantTab />}
      {tab === 2 && <ProvidersTab />}
      {tab === 3 && <DangerZoneTab />}
    </Box>
  )
}
