import { ActionIcon, Paper, Stack, Tooltip } from "@mantine/core";
import { IconCameraPlus, IconMapPinPlus, IconPointer, IconTool } from "@tabler/icons-react";

export type ToolMode = "browse" | "add-manual" | "place-photo" | "place-work-marker";

interface Props {
  mode: ToolMode;
  onChangeMode: (mode: ToolMode) => void;
  /** When non-null, the user has picked a pending photo from the panel and
   *  can enter "place-photo" mode by clicking the camera button. When null,
   *  the camera button is disabled (with a tooltip explaining how to enable it). */
  pendingPlacementId: number | null;
  /** rutenummer of the currently focused route. place-work-marker is disabled
   *  when null because every marker must be attached to a route. */
  focusedRoute: string | null;
}

interface ToolButtonProps {
  active: boolean;
  label: string;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}

function ToolButton({ active, label, disabled, onClick, children }: ToolButtonProps) {
  return (
    <Tooltip label={label} position="right" withArrow openDelay={300}>
      <ActionIcon
        variant={active ? "filled" : "subtle"}
        color={active ? "brand" : "gray"}
        size="lg"
        onClick={onClick}
        disabled={disabled}
        aria-label={label}
      >
        {children}
      </ActionIcon>
    </Tooltip>
  );
}

export default function FloatingToolbar({ mode, onChangeMode, pendingPlacementId, focusedRoute }: Props) {
  return (
    <Paper className="floating-toolbar" shadow="md" p={4} radius="md" withBorder>
      <Stack gap={4}>
        <ToolButton
          active={mode === "browse"}
          label="Velg / browse"
          onClick={() => onChangeMode("browse")}
        >
          <IconPointer size={18} />
        </ToolButton>
        <ToolButton
          active={mode === "add-manual"}
          label="Plassér manuelt skilt (klikk en rute)"
          onClick={() => onChangeMode(mode === "add-manual" ? "browse" : "add-manual")}
        >
          <IconMapPinPlus size={18} />
        </ToolButton>
        <ToolButton
          active={mode === "place-photo"}
          label={pendingPlacementId == null
            ? "Velg først et ventende bilde i bildepanelet"
            : "Plassér valgt bilde (klikk på kartet)"}
          disabled={pendingPlacementId == null && mode !== "place-photo"}
          onClick={() => onChangeMode(mode === "place-photo" ? "browse" : "place-photo")}
        >
          <IconCameraPlus size={18} />
        </ToolButton>
        <ToolButton
          active={mode === "place-work-marker"}
          label={focusedRoute == null
            ? "Velg først en rute"
            : `Marker arbeidsbehov på ${focusedRoute} (klikk på kartet)`}
          disabled={focusedRoute == null && mode !== "place-work-marker"}
          onClick={() => onChangeMode(mode === "place-work-marker" ? "browse" : "place-work-marker")}
        >
          <IconTool size={18} />
        </ToolButton>
      </Stack>
    </Paper>
  );
}
