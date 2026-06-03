import React from "react";
import ReactDOM from "react-dom/client";
import { MantineProvider, createTheme } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import FieldApp from "./FieldApp";

import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";

// Touch-first field app for phones. Separate entry from the desktop app; shares
// the brand palette so it looks consistent.
const theme = createTheme({
  primaryColor: "brand",
  primaryShade: 7,
  colors: {
    brand: [
      "#f0f4f8", "#d9e2ec", "#bcccdc", "#9fb3c8", "#829ab1",
      "#627d98", "#486581", "#1a3a5c", "#142e49", "#0e2236",
    ],
  },
  fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
  defaultRadius: "md",
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="light">
      <Notifications position="top-center" />
      <FieldApp />
    </MantineProvider>
  </React.StrictMode>,
);
