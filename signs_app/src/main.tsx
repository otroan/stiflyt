import React from "react";
import ReactDOM from "react-dom/client";
import { MantineProvider, createTheme } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import App from "./App";

// Mantine base + notifications stylesheets. Imported once at the root.
import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import "./styles.css";

// Theme matched to the current navy palette so we can migrate components
// piecewise without visual whiplash. `primaryColor` is a Mantine color name;
// extending the palette gives us the existing #1a3a5c as `brand.7`.
const theme = createTheme({
  primaryColor: "brand",
  primaryShade: 7,
  colors: {
    brand: [
      "#f0f4f8",
      "#d9e2ec",
      "#bcccdc",
      "#9fb3c8",
      "#829ab1",
      "#627d98",
      "#486581",
      "#1a3a5c", // shade 7 — matches the original topbar background
      "#142e49",
      "#0e2236",
    ],
  },
  fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
  defaultRadius: "sm",
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="light">
      <Notifications position="top-right" />
      <App />
    </MantineProvider>
  </React.StrictMode>,
);
